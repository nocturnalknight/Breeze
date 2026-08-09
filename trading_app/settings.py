from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = Path("data") / "trading_app.sqlite3"


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

    @classmethod
    def from_env(cls) -> "AppSettings":
        configured_path = Path(os.getenv("TRADING_APP_DB_PATH", str(DEFAULT_DB_PATH)))
        db_path = configured_path if configured_path.is_absolute() else BASE_DIR / configured_path
        return cls(
            title=os.getenv("TRADING_APP_TITLE", "Personal Trading Desk"),
            host=os.getenv("TRADING_APP_HOST", "127.0.0.1"),
            port=int(os.getenv("TRADING_APP_PORT", "8000")),
            db_path=db_path,
            default_cash=float(os.getenv("TRADING_APP_DEFAULT_CASH", "250000")),
            api_key=os.getenv("BREEZE_API_KEY"),
            api_secret=os.getenv("BREEZE_API_SECRET"),
            session_token=os.getenv("BREEZE_SESSION_TOKEN"),
        )

    @property
    def broker_configured(self) -> bool:
        return bool(self.api_key and self.api_secret and self.session_token)
