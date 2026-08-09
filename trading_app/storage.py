from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from trading_app.settings import AppSettings


SCHEMA = """
CREATE TABLE IF NOT EXISTS profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    display_name TEXT NOT NULL,
    trading_style TEXT NOT NULL,
    preferred_exchange TEXT NOT NULL,
    max_open_positions INTEGER NOT NULL,
    max_position_value REAL NOT NULL,
    max_drawdown_limit REAL NOT NULL,
    default_order_quantity INTEGER NOT NULL,
    paper_starting_cash REAL NOT NULL,
    paper_cash_balance REAL NOT NULL,
    notes TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    product_type TEXT NOT NULL DEFAULT 'cash',
    notes TEXT NOT NULL DEFAULT '',
    last_price REAL,
    last_synced_at TEXT,
    UNIQUE(symbol, exchange, product_type)
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    product_type TEXT NOT NULL DEFAULT 'cash',
    trigger_type TEXT NOT NULL,
    trigger_price REAL NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    product_type TEXT NOT NULL DEFAULT 'cash',
    side TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price REAL NOT NULL,
    order_value REAL NOT NULL,
    status TEXT NOT NULL,
    realized_pnl REAL NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_positions (
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    product_type TEXT NOT NULL DEFAULT 'cash',
    quantity INTEGER NOT NULL,
    avg_price REAL NOT NULL,
    last_price REAL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(symbol, exchange, product_type)
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class TradingAppStore:
    def __init__(self, settings: AppSettings):
        self.db_path = Path(settings.db_path)
        self.settings = settings

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        now = utc_now()
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            connection.execute(
                """
                INSERT OR IGNORE INTO profile (
                    id,
                    display_name,
                    trading_style,
                    preferred_exchange,
                    max_open_positions,
                    max_position_value,
                    max_drawdown_limit,
                    default_order_quantity,
                    paper_starting_cash,
                    paper_cash_balance,
                    notes,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    1,
                    "Trader",
                    "Discretionary swing",
                    "NSE",
                    5,
                    50000.0,
                    15000.0,
                    1,
                    self.settings.default_cash,
                    self.settings.default_cash,
                    "",
                    now,
                ),
            )
            connection.commit()

    def get_profile(self) -> Dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM profile WHERE id = 1").fetchone()
        return self._row_to_dict(row)

    def update_profile(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        if not updates:
            return self.get_profile()

        now = utc_now()
        columns = []
        parameters = []
        for key, value in updates.items():
            columns.append(f"{key} = ?")
            parameters.append(value)
        columns.append("updated_at = ?")
        parameters.append(now)
        parameters.append(1)

        with self._connect() as connection:
            connection.execute(
                f"UPDATE profile SET {', '.join(columns)} WHERE id = ?",
                parameters,
            )
            connection.commit()
        return self.get_profile()

    def has_paper_activity(self) -> bool:
        with self._connect() as connection:
            order_count = connection.execute("SELECT COUNT(*) FROM paper_orders").fetchone()[0]
            position_count = connection.execute("SELECT COUNT(*) FROM paper_positions").fetchone()[0]
        return bool(order_count or position_count)

    def list_watchlist(self) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM watchlist ORDER BY exchange, symbol"
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_watchlist_item(self, item_id: int) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM watchlist WHERE id = ?",
                (item_id,),
            ).fetchone()
        return self._row_to_dict(row)

    def upsert_watchlist(self, item: Dict[str, Any]) -> Dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO watchlist (
                    symbol,
                    exchange,
                    product_type,
                    notes,
                    last_price,
                    last_synced_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, exchange, product_type) DO UPDATE SET
                    notes = CASE
                        WHEN excluded.notes = '' THEN watchlist.notes
                        ELSE excluded.notes
                    END,
                    last_price = COALESCE(excluded.last_price, watchlist.last_price),
                    last_synced_at = COALESCE(excluded.last_synced_at, watchlist.last_synced_at)
                """,
                (
                    item["symbol"],
                    item["exchange"],
                    item["product_type"],
                    item.get("notes", ""),
                    item.get("last_price"),
                    item.get("last_synced_at"),
                ),
            )
            connection.commit()
            row = connection.execute(
                """
                SELECT * FROM watchlist
                WHERE symbol = ? AND exchange = ? AND product_type = ?
                """,
                (item["symbol"], item["exchange"], item["product_type"]),
            ).fetchone()
        return self._row_to_dict(row)

    def delete_watchlist_item(self, item_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM watchlist WHERE id = ?", (item_id,))
            connection.commit()

    def update_watchlist_price(self, item_id: int, price: float) -> Dict[str, Any]:
        timestamp = utc_now()
        with self._connect() as connection:
            connection.execute(
                "UPDATE watchlist SET last_price = ?, last_synced_at = ? WHERE id = ?",
                (price, timestamp, item_id),
            )
            connection.commit()
        return self.get_watchlist_item(item_id)

    def create_alert(self, alert: Dict[str, Any]) -> Dict[str, Any]:
        created_at = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO alerts (
                    symbol,
                    exchange,
                    product_type,
                    trigger_type,
                    trigger_price,
                    note,
                    active,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert["symbol"],
                    alert["exchange"],
                    alert["product_type"],
                    alert["trigger_type"],
                    alert["trigger_price"],
                    alert.get("note", ""),
                    1,
                    created_at,
                ),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM alerts WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return self._row_to_dict(row)

    def list_alerts(self) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM alerts ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def delete_alert(self, alert_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
            connection.commit()

    def list_positions(self) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM paper_positions ORDER BY exchange, symbol"
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_position(self, symbol: str, exchange: str, product_type: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM paper_positions
                WHERE symbol = ? AND exchange = ? AND product_type = ?
                """,
                (symbol, exchange, product_type),
            ).fetchone()
        return self._row_to_dict(row)

    def save_position(self, position: Dict[str, Any]) -> Dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO paper_positions (
                    symbol,
                    exchange,
                    product_type,
                    quantity,
                    avg_price,
                    last_price,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, exchange, product_type) DO UPDATE SET
                    quantity = excluded.quantity,
                    avg_price = excluded.avg_price,
                    last_price = excluded.last_price,
                    updated_at = excluded.updated_at
                """,
                (
                    position["symbol"],
                    position["exchange"],
                    position["product_type"],
                    position["quantity"],
                    position["avg_price"],
                    position.get("last_price"),
                    position["updated_at"],
                ),
            )
            connection.commit()
        return self.get_position(position["symbol"], position["exchange"], position["product_type"])

    def delete_position(self, symbol: str, exchange: str, product_type: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                DELETE FROM paper_positions
                WHERE symbol = ? AND exchange = ? AND product_type = ?
                """,
                (symbol, exchange, product_type),
            )
            connection.commit()

    def touch_position_price(self, symbol: str, exchange: str, product_type: str, price: float) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE paper_positions
                SET last_price = ?, updated_at = ?
                WHERE symbol = ? AND exchange = ? AND product_type = ?
                """,
                (price, utc_now(), symbol, exchange, product_type),
            )
            connection.commit()

    def create_order(self, order: Dict[str, Any]) -> Dict[str, Any]:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO paper_orders (
                    symbol,
                    exchange,
                    product_type,
                    side,
                    quantity,
                    price,
                    order_value,
                    status,
                    realized_pnl,
                    notes,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order["symbol"],
                    order["exchange"],
                    order["product_type"],
                    order["side"],
                    order["quantity"],
                    order["price"],
                    order["order_value"],
                    order["status"],
                    order["realized_pnl"],
                    order.get("notes", ""),
                    order["created_at"],
                ),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM paper_orders WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return self._row_to_dict(row)

    def list_orders(self, limit: Optional[int] = 20) -> List[Dict[str, Any]]:
        query = "SELECT * FROM paper_orders ORDER BY created_at DESC"
        parameters: List[Any] = []
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def sum_realized_pnl(self) -> float:
        with self._connect() as connection:
            result = connection.execute(
                "SELECT COALESCE(SUM(realized_pnl), 0) FROM paper_orders"
            ).fetchone()[0]
        return float(result or 0)

    def update_cash_balance(self, cash_balance: float) -> Dict[str, Any]:
        return self.update_profile({"paper_cash_balance": cash_balance})

    def reset_paper_account(self) -> Dict[str, Any]:
        profile = self.get_profile()
        with self._connect() as connection:
            connection.execute("DELETE FROM paper_orders")
            connection.execute("DELETE FROM paper_positions")
            connection.execute(
                """
                UPDATE profile
                SET paper_cash_balance = ?, updated_at = ?
                WHERE id = 1
                """,
                (profile["paper_starting_cash"], utc_now()),
            )
            connection.commit()
        return self.get_profile()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
        return dict(row) if row is not None else None
