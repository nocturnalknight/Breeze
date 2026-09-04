from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = Path("data") / "trading_app.sqlite3"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppSettings:
    title: str
    host: str
    port: int
    db_path: Path
    default_cash: float
    api_key: Optional[str]
    api_secret: Optional[str]
    session_token: Optional[str]
    registered_static_ip: Optional[str]
    vps_domain: Optional[str]
    frontend_origin: str

    @classmethod
    def from_env(cls) -> "AppSettings":
        configured_path = Path(os.getenv("TRADING_APP_DB_PATH", str(DEFAULT_DB_PATH)))
        db_path = configured_path if configured_path.is_absolute() else BASE_DIR / configured_path
        settings = cls(
            title=os.getenv("TRADING_APP_TITLE", "Personal Trading Desk"),
            host=os.getenv("TRADING_APP_HOST", "127.0.0.1"),
            port=int(os.getenv("TRADING_APP_PORT", "8000")),
            db_path=db_path,
            default_cash=float(os.getenv("TRADING_APP_DEFAULT_CASH", "250000")),
            api_key=os.getenv("BREEZE_API_KEY"),
            api_secret=os.getenv("BREEZE_API_SECRET"),
            session_token=os.getenv("BREEZE_SESSION_TOKEN"),
            registered_static_ip=os.getenv("REGISTERED_STATIC_IP") or None,
            vps_domain=os.getenv("VPS_DOMAIN") or None,
            frontend_origin=os.getenv("FRONTEND_ORIGIN", "http://localhost:3000"),
        )
        settings._warn_on_ip_mismatch()
        return settings

    @property
    def broker_configured(self) -> bool:
        return bool(self.api_key and self.api_secret and self.session_token)

    def _warn_on_ip_mismatch(self) -> None:
        if not self.registered_static_ip:
            return
        try:
            import httpx

            response = httpx.get("https://api.ipify.org", timeout=5.0)
            response.raise_for_status()
            outbound_ip = response.text.strip()
        except Exception as exc:
            logger.warning("Could not verify outbound IP against REGISTERED_STATIC_IP: %s", exc)
            return
        if outbound_ip != self.registered_static_ip:
            logger.warning(
                "Outbound IP %s does not match REGISTERED_STATIC_IP %s. "
                "This is expected on a dev machine; Breeze order calls will fail unless this "
                "matches the whitelisted VPS IP.",
                outbound_ip,
                self.registered_static_ip,
            )
