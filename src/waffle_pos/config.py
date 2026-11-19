"""Process configuration, read from environment variables (prefix ``WB_``) or a ``.env`` file.

Shop-level settings that the owner edits in the app (GST, target, Google Sheet) live in the
database as feature-module settings; see :mod:`waffle_pos.modules`.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WB_", env_file=".env", extra="ignore")

    data_dir: Path = PROJECT_ROOT / "data"
    host: str = "0.0.0.0"  # noqa: S104 - reachable from tablets on the shop Wi-Fi by design
    port: int = 4000
    timezone: str = "Asia/Kolkata"
    frontend_dist: Path = PROJECT_ROOT / "frontend" / "dist"
    sync_interval_seconds: int | None = None  # None: use the Google Sheet module's interval_minutes
    start_sync_loop: bool = True
    # Extra host names the POS may be opened by (comma-separated), e.g. "pos.waffle-bros.in".
    # IP addresses, single-word names (localhost, shop-pc) and *.local names always work.
    allowed_hosts: str = ""
    max_body_bytes: int = 1_000_000
    # Proxies whose X-Forwarded-For header is believed, so the PIN lockout sees each tablet's own
    # address. In Docker the `web` (nginx) container is the only way in, so compose sets "*".
    forwarded_allow_ips: str = "127.0.0.1"

    @property
    def allowed_host_list(self) -> list[str]:
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]

    @property
    def db_path(self) -> Path:
        return self.data_dir / "waffle-bros.db"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path.as_posix()}"


@lru_cache
def get_config() -> AppConfig:
    return AppConfig()
