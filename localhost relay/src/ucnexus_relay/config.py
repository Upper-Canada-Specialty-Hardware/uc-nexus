"""Config loading from config.toml (Python 3.11 tomllib + pydantic validation)."""

import tomllib
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

# config.py lives at <root>/src/ucnexus_relay/config.py — config.toml is at <root>/config.toml
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.toml"


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


class GpCfg(BaseModel):
    default_company: str = "TUBC"
    allowed_companies: list[str] = ["TUBC"]
    # company -> paired custom warehouse DB that holds WHRECLINE101 (the table the company dashboards
    # read). A company with no entry gets GP-only receipts (no WHRECLINE101 write). Sandboxes have none.
    custom_db: dict[str, str] = {}


class LoggingCfg(BaseModel):
    level: str = "INFO"
    file: str = "relay.log"


class Settings(BaseModel):
    server: ServerCfg = ServerCfg()
    auth: AuthCfg
    cors: CorsCfg = CorsCfg()
    sql: SqlCfg
    gp: GpCfg = GpCfg()
    logging: LoggingCfg = LoggingCfg()


@lru_cache
def get_settings(path: str | None = None) -> Settings:
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        raise RuntimeError(
            f"config file not found: {cfg_path} — copy config.example.toml to config.toml and set the shared_secret"
        )
    with open(cfg_path, "rb") as f:
        data = tomllib.load(f)
    return Settings(**data)
