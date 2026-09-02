"""Config loading from config.toml (Python 3.11 tomllib + pydantic validation)."""

import os
import sys
import tomllib
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, BaseModel, Field

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


def _default_fixture_path() -> Path:
    """The snapshot bundled with the source tree: <root>/fixtures/gp-snapshot.json, resolved relative to
    this package (config.py is <root>/src/ucnexus_relay/config.py) so the Linux container finds it
    wherever the image put the tree."""
    return Path(__file__).resolve().parents[2] / "fixtures" / "gp-snapshot.json"


DEFAULT_FIXTURE_PATH = _default_fixture_path()


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
    # The GP system database, which holds the company master SY01500 - the list of companies this relay
    # serves is read from there rather than hand-maintained (see companies.py). Baked like the rest of
    # [sql]: it is GP's own name for that database, not a per-workstation choice.
    system_db: str = "DYNAMICS"


class BuyersCfg(BaseModel):
    # Fallback buyer when the Create PO request omits buyer_id (normally the UI sends one picked from
    # GET /buyers). The value MUST be a REGISTERED GP buyer (POP00101) - eConnect taPoHdr rejects an
    # unregistered BUYERID (error 269). A device hostname is NOT a registered buyer, so there's no
    # use_hostname option. Resolution order: by_host -> by_login -> default.
    default: str | None = None
    by_host: dict[str, str] = {}  # device hostname -> registered buyer
    by_login: dict[str, str] = {}  # SQL/SSPI login -> registered buyer


class GpCfg(BaseModel):
    # How GP is reached. "sql" is the workstation relay: pyodbc to the real company databases. "fixture"
    # serves every op out of a checked-in JSON snapshot instead, with writes kept in memory, so the relay
    # can run in a Linux container (a Railway preview environment) with no GP and no ODBC at all - see
    # fixture_ops.py. Env override: UCNEXUS_RELAY_MODE.
    mode: str = "sql"
    # Where that snapshot lives. None means the bundled one (_default_fixture_path). Env override:
    # UCNEXUS_RELAY_FIXTURE_PATH.
    fixture_path: str | None = None
    # company -> paired custom warehouse DB that holds WHRECLINE101 (the table the company dashboards
    # read). A company with no entry gets GP-only receipts (no WHRECLINE101 write). Sandboxes have none.
    # Baked dev default: the prod pairings (applied only to a discovered company that has an entry).
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
# verifiable before it merges - but only against the sandbox companies, so the worst a test backend can
# do is write to a sandbox. Baked deliberately: an operator-editable value here would be one typo away
# from pointing a PR backend at a live GP company, which is the only thing making this safe (#414).
# Both sandboxes are listed because UCSH-side work (a second company's job, cost codes, receipts) is
# only reproducible against TUCSH, and testing it otherwise means aiming a PR backend at live UCSH.
NON_PRIMARY_ALLOWED_COMPANIES = ["TUBC", "TUCSH"]


def _normalize_url(url: str) -> str:
    return (url or "").strip().rstrip("/").lower()


def is_primary_backend_url(url: str) -> bool:
    """Whether this channel is the production backend. Tolerates a trailing slash and case so a
    cosmetic difference in config.toml cannot silently demote production to a restricted channel; a
    genuinely different host never matches."""
    return _normalize_url(url) == _normalize_url(PRODUCTION_BACKEND_URL)


def channel_allowed_companies(url: str) -> list[str] | None:
    """The GP companies this channel may target, or None for unrestricted (the production channel,
    which reaches every company this relay discovered, as it always has)."""
    return None if is_primary_backend_url(url) else list(NON_PRIMARY_ALLOWED_COMPANIES)


def primary_url(urls: list[str]) -> str:
    """The production URL among `urls`, else the first one. Single definition of "which channel stands
    for this relay" - both the /health snapshot and the enroll wizard's URL derivation need it, and two
    copies could drift into disagreeing about which channel is production."""
    return next((u for u in urls if is_primary_backend_url(u)), urls[0] if urls else "")


class ChannelCfg(BaseModel):
    # Outbound wss URL(s) to UC Nexus backend relay gateways. A bare string is one channel (every
    # config.toml written before #414 is exactly this); a list opens one connection per URL, so a
    # workstation can serve a Railway PR environment WITHOUT dropping production - the reason a list
    # exists at all. Empty (blank string, or empty list) disables the channel entirely and the relay
    # runs only its inbound HTTP server. Baked dev default: production alone.
    backend_url: str | list[str] = PRODUCTION_BACKEND_URL
    # ADDITIVE test backends, and the way an operator should normally add one. Overriding backend_url
    # means retyping production's URL alongside the new one, and a single wrong character there does
    # not fail loudly - it makes is_primary_backend_url False, so the PRODUCTION channel silently
    # inherits the sandbox pin and every real UBC/UCSH job is refused. Listing only the extra URL here
    # cannot express that mistake, because production's URL comes from the baked default untouched.
    extra_backend_urls: list[str] = []
    # Accept the preview-environment list the PRODUCTION backend pushes down the socket it already
    # holds, and dial those too, so a PR environment stops needing a hand edit on this machine. Only
    # ADDS to the two keys above, only accepts the fixed preview hostname shape, and a pushed channel
    # can never be the primary one - so it inherits the sandbox company pin like any other non-primary
    # channel. Off means this relay dials exactly what is written here. The old key name
    # (discover_preview_backends, from when the relay polled for the list) still sets it, so a
    # config.toml written before the push model keeps meaning what it said.
    accept_pushed_preview_backends: bool = Field(
        default=True,
        validation_alias=AliasChoices("accept_pushed_preview_backends", "discover_preview_backends"),
    )
    # the `websockets` client's own ping_interval/ping_timeout default to 20s/20s, which already
    # satisfies the ~20s keepalive the channel needs to hold a corporate-proxy idle timeout open -
    # these just make that tunable without a code change.
    ping_interval: float = 20.0
    ping_timeout: float = 20.0
    reconnect_min_seconds: float = 1.0
    reconnect_max_seconds: float = 30.0

    @property
    def backend_urls(self) -> list[str]:
        """Every configured channel URL, in one shape: de-duplicated, non-blank, backend_url first then
        extra_backend_urls. Duplicates are dropped because two channels to the same backend would fight
        over its single connection slot, each closing the other with 4409 forever - which is also what
        makes listing production in BOTH keys harmless rather than self-defeating."""
        raw = [self.backend_url] if isinstance(self.backend_url, str) else list(self.backend_url)
        raw = raw + list(self.extra_backend_urls)
        seen: set[str] = set()
        urls: list[str] = []
        for candidate in raw:
            url = (candidate or "").strip()
            key = _normalize_url(url)
            if url and key not in seen:
                seen.add(key)
                urls.append(url)
        return urls


UPDATE_CHANNELS = ("stable", "latest")


class UpdateCfg(BaseModel):
    # Which GitHub releases this workstation will install. "stable" takes only full releases; "latest"
    # also takes prereleases, which is how a build is proven on one workstation before it is promoted
    # (gh release edit <tag> --prerelease=false) to the rest of the fleet. Deliberately a plain string:
    # a typo here must not make config.toml unreadable and keep serve from starting, which would take
    # production's channel down over an update preference. updater.update_channel() treats anything
    # but "latest" as "stable" and logs the unknown value so the promote step is not mistaken for broken.
    channel: str = "stable"


class Settings(BaseModel):
    server: ServerCfg = ServerCfg()
    auth: AuthCfg = AuthCfg()
    cors: CorsCfg = CorsCfg()
    sql: SqlCfg = SqlCfg()
    gp: GpCfg = GpCfg()
    logging: LoggingCfg = LoggingCfg()
    channel: ChannelCfg = ChannelCfg()
    update: UpdateCfg = UpdateCfg()


# Environment overrides, each winning over whatever config.toml holds. They exist for the one place a
# config.toml cannot be written by hand: the relay running as a Linux container in a Railway preview
# environment, serving GP out of a fixture snapshot (see fixture_ops.py). On a workstation nothing sets
# these and config.toml is the only source, exactly as before.
#
#   UCNEXUS_RELAY_MODE          -> [gp] mode              "sql" (real GP over ODBC) or "fixture"
#   UCNEXUS_RELAY_FIXTURE_PATH  -> [gp] fixture_path      snapshot to serve; unset = the bundled one
#   UCNEXUS_RELAY_SHARED_SECRET -> [auth] shared_secret   PLAINTEXT; never DPAPI-decrypted
#   UCNEXUS_RELAY_BACKEND_URL   -> [channel] backend_url  the single backend to dial
#   UCNEXUS_RELAY_LOG_FILE      -> [logging] file         "-" means stdout only, no relay.log on disk


def _section(data: dict, name: str) -> dict:
    section = data.get(name)
    if not isinstance(section, dict):
        section = {}
        data[name] = section
    return section


def _apply_env_overrides(data: dict) -> None:
    """Fold the UCNEXUS_RELAY_* variables into the parsed config, in place."""
    mode = os.environ.get("UCNEXUS_RELAY_MODE")
    fixture_path = os.environ.get("UCNEXUS_RELAY_FIXTURE_PATH")
    if mode or fixture_path:
        gp = _section(data, "gp")
        if mode:
            gp["mode"] = mode.strip().lower()
        if fixture_path:
            gp["fixture_path"] = fixture_path

    backend_url = os.environ.get("UCNEXUS_RELAY_BACKEND_URL")
    if backend_url:
        _section(data, "channel")["backend_url"] = backend_url.strip()

    log_file = os.environ.get("UCNEXUS_RELAY_LOG_FILE")
    if log_file:
        _section(data, "logging")["file"] = log_file.strip()


@lru_cache
def get_settings(path: str | None = None) -> Settings:
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    data: dict = {}
    if cfg_path.exists():
        with open(cfg_path, "rb") as f:
            data = tomllib.load(f)
    # A missing file is first run / not yet enrolled, and now also the container: every setting except the
    # secret is baked into the defaults above, so build from them with an empty secret rather than
    # failing. The app opens Setup to enroll; serve runs its local HTTP server but brokers nothing until
    # a config with a secret exists.
    #
    # The env secret is taken VERBATIM and replaces the file's, deliberately ahead of the decrypt below:
    # it is plaintext by definition (a container has no DPAPI), and an enrolled config.toml carried into
    # a non-Windows image would otherwise fail the decrypt on a value the environment was about to
    # override anyway. The file's own value still decrypts as it always has - dpapi.unprotect passes a
    # plaintext (dev) value through untouched and only demands Windows for a real enc:dpapi: blob.
    env_secret = os.environ.get("UCNEXUS_RELAY_SHARED_SECRET")
    if env_secret is not None:
        _section(data, "auth")["shared_secret"] = env_secret
    else:
        auth = data.get("auth")
        if isinstance(auth, dict) and isinstance(auth.get("shared_secret"), str):
            auth["shared_secret"] = dpapi.unprotect(auth["shared_secret"])
    _apply_env_overrides(data)
    return Settings(**data)
