"""Config loading from config.toml (Python 3.11 tomllib + pydantic validation)."""

import sys
import tomllib
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from . import dpapi


def _default_config_path() -> Path:
    # When packaged by PyInstaller, __file__ points into the temp extraction dir, so config.toml is
    # resolved next to the .exe instead. In a dev checkout it sits at <root>/config.toml
    # (config.py is <root>/src/ucnexus_relay/config.py).
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "config.toml"
    return Path(__file__).resolve().parents[2] / "config.toml"


DEFAULT_CONFIG_PATH = _default_config_path()


class ServerCfg(BaseModel):
    host: str = "127.0.0.1"
    port: int = 7321


class AuthCfg(BaseModel):
    shared_secret: str


class CorsCfg(BaseModel):
    allowed_origins: list[str] = []


class SqlCfg(BaseModel):
    server: str
    driver: str = "ODBC Driver 17 for SQL Server"
    trusted_connection: bool = True
    encrypt: str = "yes"
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
    custom_db: dict[str, str] = {}
    buyers: BuyersCfg = BuyersCfg()


class LoggingCfg(BaseModel):
    level: str = "INFO"
    file: str = "relay.log"


class ChannelCfg(BaseModel):
    # Outbound wss URL to the UC Nexus backend's relay gateway, e.g. "wss://backend.example/relay-link".
    # Empty disables the channel (the relay just runs its existing inbound HTTP server).
    backend_url: str = ""
    # the `websockets` client's own ping_interval/ping_timeout default to 20s/20s, which already
    # satisfies the ~20s keepalive the channel needs to hold a corporate-proxy idle timeout open -
    # these just make that tunable without a code change.
    ping_interval: float = 20.0
    ping_timeout: float = 20.0
    reconnect_min_seconds: float = 1.0
    reconnect_max_seconds: float = 30.0


class Settings(BaseModel):
    server: ServerCfg = ServerCfg()
    auth: AuthCfg
    cors: CorsCfg = CorsCfg()
    sql: SqlCfg
    gp: GpCfg = GpCfg()
    logging: LoggingCfg = LoggingCfg()
    channel: ChannelCfg = ChannelCfg()


@lru_cache
def get_settings(path: str | None = None) -> Settings:
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        raise RuntimeError(
            f"config file not found: {cfg_path} — copy config.example.toml to config.toml and set the shared_secret"
        )
    with open(cfg_path, "rb") as f:
        data = tomllib.load(f)
    # the shared_secret is DPAPI-encrypted at rest (see ucnexus_relay.dpapi); decrypt on read so the
    # rest of the app only ever sees the plaintext. a plaintext (dev) value passes through unchanged.
    auth = data.get("auth")
    if isinstance(auth, dict) and isinstance(auth.get("shared_secret"), str):
        auth["shared_secret"] = dpapi.unprotect(auth["shared_secret"])
    return Settings(**data)
