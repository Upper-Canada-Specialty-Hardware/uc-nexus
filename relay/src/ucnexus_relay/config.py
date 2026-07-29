"""Config loading from config.toml (Python 3.11 tomllib + pydantic validation)."""

import os
import sys
import tomllib
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from . import dpapi


def _default_config_path() -> Path:
    # Packaged: a FIXED per-user path (%LOCALAPPDATA%\UCNexusRelay\config.toml), NOT next to the exe, so
    # the exe can be run from anywhere (Downloads, a USB stick) and still find the enrolled config - the
    # single-file-distributable model. In a dev checkout it sits at <root>/config.toml
    # (config.py is <root>/src/ucnexus_relay/config.py).
    if getattr(sys, "frozen", False):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "UCNexusRelay" / "config.toml"
    return Path(__file__).resolve().parents[2] / "config.toml"


DEFAULT_CONFIG_PATH = _default_config_path()

# The determined GP companies an operator may pick from in the Setup tab. Dev-determined - edit here to
# change what's offered; allowed_companies + default_company in the wizard are chosen from this list.
KNOWN_COMPANIES = ["TUBC", "TUCSH", "UBC", "UCSH"]


class ServerCfg(BaseModel):
    host: str = "127.0.0.1"
    port: int = 7321


class AuthCfg(BaseModel):
    # Empty until enrolled. When it's blank the desktop app boots to the Setup tab; serve brokers nothing
    # (no outbound channel) until enrollment writes a real secret.
    shared_secret: str = ""


class CorsCfg(BaseModel):
    # Baked: the Nexus frontend origins (dev-determined infra, not a per-workstation setting).
    allowed_origins: list[str] = [
        "https://frontend-production-34fc.up.railway.app",
        "https://ucnexus-frontend-production.up.railway.app",
        "http://localhost:5173",
        "http://localhost:8000",
    ]


class SqlCfg(BaseModel):
    # Baked dev defaults: SQL server + driver are dev-determined infra, not per-workstation settings, so a
    # workstation's config.toml no longer needs [sql]. Change here (dev) only if the infra actually moves.
    server: str = "10.0.0.246,1435"
    driver: str = "ODBC Driver 17 for SQL Server"
    trusted_connection: bool = True
    encrypt: str = "yes"
    # Encrypt=yes but TrustServerCertificate=yes: the connection is encrypted, but the SQL Server cert is
    # NOT validated (a self-signed cert is accepted). Acceptable for the trusted internal LAN this relay
    # runs on; if the SQL box gets a CA-issued/pinned cert, set this False to actually validate against it.
    trust_server_certificate: bool = True
    connection_timeout: int = 10
    command_timeout: int = 30


class BuyersCfg(BaseModel):
    # Fallback buyer when the Create PO request omits buyer_id (normally the UI sends one picked from
    # GET /buyers). The value MUST be a REGISTERED GP buyer (POP00101) - eConnect taPoHdr rejects an
    # unregistered BUYERID (error 269). A device hostname is NOT a registered buyer, so there's no
    # use_hostname option. Resolution order: by_host -> by_login -> default.
    default: str | None = None
    by_host: dict[str, str] = {}   # device hostname -> registered buyer
    by_login: dict[str, str] = {}  # SQL/SSPI login -> registered buyer


class GpCfg(BaseModel):
    default_company: str = "TUBC"
    allowed_companies: list[str] = ["TUBC"]
    # company -> paired custom warehouse DB that holds WHRECLINE101 (the table the company dashboards
    # read). A company with no entry gets GP-only receipts (no WHRECLINE101 write). Sandboxes have none.
    # Baked dev default: the prod pairings (applied only when that company is also allowed).
    custom_db: dict[str, str] = {"UBC": "PMUBC", "UCSH": "PMUCSH"}
    buyers: BuyersCfg = BuyersCfg()


class LoggingCfg(BaseModel):
    level: str = "INFO"
    file: str = "relay.log"


# THE production backend. Identity - not list position - is what makes a channel the primary one, so
# reordering backend_url can never accidentally hand a test backend unrestricted company access.
PRODUCTION_BACKEND_URL = "wss://backend-production-7866.up.railway.app/relay-link"

# What a NON-PRIMARY channel (a Railway PR environment, a local dev backend) may target. Reads AND
# writes are served on those channels - that is the whole point, a PR that touches GP has to be
# verifiable before it merges - but only against the sandbox company, so the worst a test backend can
# do is write to TUBC. Baked deliberately: an operator-editable value here would be one typo away from
# pointing a PR backend at a live GP company, which is the only thing making this safe (#414).
NON_PRIMARY_ALLOWED_COMPANIES = ["TUBC"]


def _normalize_url(url: str) -> str:
    return (url or "").strip().rstrip("/").lower()


def is_primary_backend_url(url: str) -> bool:
    """Whether this channel is the production backend. Tolerates a trailing slash and case so a
    cosmetic difference in config.toml cannot silently demote production to a restricted channel; a
    genuinely different host never matches."""
    return _normalize_url(url) == _normalize_url(PRODUCTION_BACKEND_URL)


def channel_allowed_companies(url: str) -> list[str] | None:
    """The GP companies this channel may target, or None for unrestricted (the production channel,
    which is governed by [gp] allowed_companies alone, as it always has been)."""
    return None if is_primary_backend_url(url) else list(NON_PRIMARY_ALLOWED_COMPANIES)


class ChannelCfg(BaseModel):
    # Outbound wss URL(s) to UC Nexus backend relay gateways. A bare string is one channel (every
    # config.toml written before #414 is exactly this); a list opens one connection per URL, so a
    # workstation can serve a Railway PR environment WITHOUT dropping production - the reason a list
    # exists at all. Empty (blank string, or empty list) disables the channel entirely and the relay
    # runs only its inbound HTTP server. Baked dev default: production alone.
    backend_url: str | list[str] = PRODUCTION_BACKEND_URL
    # the `websockets` client's own ping_interval/ping_timeout default to 20s/20s, which already
    # satisfies the ~20s keepalive the channel needs to hold a corporate-proxy idle timeout open -
    # these just make that tunable without a code change.
    ping_interval: float = 20.0
    ping_timeout: float = 20.0
    reconnect_min_seconds: float = 1.0
    reconnect_max_seconds: float = 30.0

    @property
    def backend_urls(self) -> list[str]:
        """backend_url in its one true shape: a de-duplicated list of non-blank URLs. Duplicates are
        dropped because two channels to the same backend would fight over its single connection slot,
        each closing the other with 4409 forever."""
        raw = [self.backend_url] if isinstance(self.backend_url, str) else list(self.backend_url)
        seen: set[str] = set()
        urls: list[str] = []
        for candidate in raw:
            url = (candidate or "").strip()
            key = _normalize_url(url)
            if url and key not in seen:
                seen.add(key)
                urls.append(url)
        return urls


class Settings(BaseModel):
    server: ServerCfg = ServerCfg()
    auth: AuthCfg = AuthCfg()
    cors: CorsCfg = CorsCfg()
    sql: SqlCfg = SqlCfg()
    gp: GpCfg = GpCfg()
    logging: LoggingCfg = LoggingCfg()
    channel: ChannelCfg = ChannelCfg()


@lru_cache
def get_settings(path: str | None = None) -> Settings:
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        # First run / not yet enrolled: every setting except the secret is baked into the defaults above,
        # so build from them with an empty secret rather than failing. The app opens Setup to enroll;
        # serve runs its local HTTP server but brokers nothing until a config with a secret exists.
        return Settings()
    with open(cfg_path, "rb") as f:
        data = tomllib.load(f)
    # the shared_secret is DPAPI-encrypted at rest (see ucnexus_relay.dpapi); decrypt on read so the
    # rest of the app only ever sees the plaintext. a plaintext (dev) value passes through unchanged.
    auth = data.get("auth")
    if isinstance(auth, dict) and isinstance(auth.get("shared_secret"), str):
        auth["shared_secret"] = dpapi.unprotect(auth["shared_secret"])
    return Settings(**data)
