from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

from trading_app.broker import BreezeBroker
from trading_app.storage import TradingAppStore, utc_now


class TradingAppError(Exception):
    """Raised for recoverable validation errors in the personalized trading app."""


class TradingAppService:
    def __init__(self, store: TradingAppStore, broker: BreezeBroker):
        self.store = store
        self.broker = broker

    @property
    def broker_configured(self) -> bool:
        return self.broker.configured

    def get_dashboard(self) -> Dict[str, Any]:
        profile = self.store.get_profile()
        watchlist = self.store.list_watchlist()
        positions = self.store.list_positions()
        portfolio = self.get_portfolio_snapshot(profile=profile, positions=positions)
        alerts = self._annotate_alerts(self.store.list_alerts(), watchlist, positions)
        return {
            "profile": profile,
            "watchlist": watchlist,
            "alerts": alerts,
            "portfolio": portfolio,
            "broker_configured": self.broker_configured,
        }

    def update_profile(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        normalized: Dict[str, Any] = {}
        for key, value in updates.items():
            if value is None:
                continue
            if key == "display_name":
                normalized[key] = self._required_text(value, "Display name")
            elif key == "trading_style":
                normalized[key] = self._required_text(value, "Trading style")
            elif key == "preferred_exchange":
                normalized[key] = self._required_text(value, "Preferred exchange").upper()
            elif key == "notes":
                normalized[key] = (value or "").strip()
            elif key in {
                "max_open_positions",
                "default_order_quantity",
            }:
                normalized[key] = self._positive_int(value, key.replace("_", " "))
            elif key in {
                "max_position_value",
                "max_drawdown_limit",
                "paper_starting_cash",
            }:
                normalized[key] = self._positive_float(value, key.replace("_", " "))

        if "paper_starting_cash" in normalized and not self.store.has_paper_activity():
            normalized["paper_cash_balance"] = normalized["paper_starting_cash"]
        return self.store.update_profile(normalized)

    def add_watchlist_item(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        item = {
            "symbol": self._clean_symbol(payload["symbol"]),
            "exchange": self._clean_exchange(payload.get("exchange")),
            "product_type": self._clean_product_type(payload.get("product_type")),
            "notes": (payload.get("notes") or "").strip(),
            "last_price": payload.get("last_price"),
            "last_synced_at": payload.get("last_synced_at"),
        }
        return self.store.upsert_watchlist(item)

    def remove_watchlist_item(self, item_id: int) -> None:
        if not self.store.get_watchlist_item(item_id):
            raise TradingAppError("Watchlist item not found.")
        self.store.delete_watchlist_item(item_id)

    def update_watchlist_price(self, item_id: int, price: float) -> Dict[str, Any]:
        item = self.store.get_watchlist_item(item_id)
        if not item:
            raise TradingAppError("Watchlist item not found.")

        clean_price = round(self._positive_float(price, "price"), 2)
        self.store.touch_position_price(
            item["symbol"],
            item["exchange"],
            item["product_type"],
            clean_price,
        )
        return self.store.update_watchlist_price(item_id, clean_price)

    def refresh_watchlist_item(self, item_id: int) -> Dict[str, Any]:
        item = self.store.get_watchlist_item(item_id)
        if not item:
            raise TradingAppError("Watchlist item not found.")
        quote = self.broker.get_quote(item["symbol"], item["exchange"], item["product_type"])
        return self.update_watchlist_price(item_id, quote["price"])

    def refresh_watchlist(self) -> List[Dict[str, Any]]:
        refreshed_items = []
        for item in self.store.list_watchlist():
            refreshed_items.append(self.refresh_watchlist_item(item["id"]))
        return refreshed_items

    def add_alert(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        alert = {
            "symbol": self._clean_symbol(payload["symbol"]),
            "exchange": self._clean_exchange(payload.get("exchange")),
            "product_type": self._clean_product_type(payload.get("product_type")),
            "trigger_type": self._clean_trigger_type(payload.get("trigger_type")),
            "trigger_price": round(self._positive_float(payload["trigger_price"], "trigger price"), 2),
            "note": (payload.get("note") or "").strip(),
        }
        return self.store.create_alert(alert)

    def remove_alert(self, alert_id: int) -> None:
        existing_ids = {alert["id"] for alert in self.store.list_alerts()}
        if alert_id not in existing_ids:
            raise TradingAppError("Alert not found.")
        self.store.delete_alert(alert_id)

    def place_paper_order(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        profile = self.store.get_profile()
        symbol = self._clean_symbol(payload["symbol"])
        exchange = self._clean_exchange(payload.get("exchange"))
        product_type = self._clean_product_type(payload.get("product_type"))
        side = self._clean_side(payload.get("side"))
        quantity = self._positive_int(payload.get("quantity"), "quantity")
        price = round(self._positive_float(payload.get("price"), "price"), 2)
        order_value = round(quantity * price, 2)
        notes = (payload.get("notes") or "").strip()
        position = self.store.get_position(symbol, exchange, product_type)
        portfolio = self.get_portfolio_snapshot(profile=profile)

        if side == "buy" and portfolio["drawdown"] >= profile["max_drawdown_limit"]:
            raise TradingAppError("Max drawdown limit reached. Reset or reduce risk before adding exposure.")
        current_quantity = int(position["quantity"]) if position else 0
        resulting_position_value = round((current_quantity + quantity) * price, 2)
        if side == "buy" and resulting_position_value > profile["max_position_value"]:
            raise TradingAppError("Order value exceeds your max position value setting.")

        if side == "buy":
            if order_value > profile["paper_cash_balance"]:
                raise TradingAppError("Insufficient paper cash for this order.")
            open_positions = self.store.list_positions()
            is_new_position = position is None or position["quantity"] == 0
            if is_new_position and len(open_positions) >= profile["max_open_positions"]:
                raise TradingAppError("Max open positions reached.")
            executed_order = self._execute_buy(
                profile=profile,
                position=position,
                symbol=symbol,
                exchange=exchange,
                product_type=product_type,
                quantity=quantity,
                price=price,
                order_value=order_value,
                notes=notes,
            )
        else:
            if position is None or position["quantity"] < quantity:
                raise TradingAppError("Not enough quantity in the paper portfolio to sell.")
            executed_order = self._execute_sell(
                profile=profile,
                position=position,
                symbol=symbol,
                exchange=exchange,
                product_type=product_type,
                quantity=quantity,
                price=price,
                order_value=order_value,
                notes=notes,
            )

        self.store.upsert_watchlist(
            {
                "symbol": symbol,
                "exchange": exchange,
                "product_type": product_type,
                "notes": "",
                "last_price": price,
                "last_synced_at": utc_now(),
            }
        )
        return {
            "order": executed_order,
            "portfolio": self.get_portfolio_snapshot(),
        }

    def reset_paper_account(self) -> Dict[str, Any]:
        profile = self.store.reset_paper_account()
        return {
            "profile": profile,
            "portfolio": self.get_portfolio_snapshot(profile=profile),
        }

    def get_portfolio_snapshot(
        self,
        profile: Dict[str, Any] | None = None,
        positions: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        profile = profile if profile is not None else self.store.get_profile()
        positions = positions if positions is not None else self.store.list_positions()
        enriched_positions = self._annotate_positions(positions)
        total_market_value = round(sum(item["market_value"] for item in enriched_positions), 2)
        total_unrealized_pnl = round(sum(item["unrealized_pnl"] for item in enriched_positions), 2)
        total_realized_pnl = round(self.store.sum_realized_pnl(), 2)
        cash_balance = round(float(profile["paper_cash_balance"]), 2)
        starting_cash = round(float(profile["paper_starting_cash"]), 2)
        account_value = round(cash_balance + total_market_value, 2)
        total_pnl = round(total_realized_pnl + total_unrealized_pnl, 2)
        return_pct = round(((account_value - starting_cash) / starting_cash) * 100, 2) if starting_cash else 0.0
        drawdown = round(max(0.0, starting_cash - account_value), 2)
        return {
            "cash_balance": cash_balance,
            "starting_cash": starting_cash,
            "account_value": account_value,
            "total_market_value": total_market_value,
            "total_unrealized_pnl": total_unrealized_pnl,
            "total_realized_pnl": total_realized_pnl,
            "total_pnl": total_pnl,
            "return_pct": return_pct,
            "drawdown": drawdown,
            "open_positions_count": len(enriched_positions),
            "positions": enriched_positions,
            "recent_orders": self.store.list_orders(),
        }

    def _execute_buy(
        self,
        profile: Dict[str, Any],
        position: Dict[str, Any] | None,
        symbol: str,
        exchange: str,
        product_type: str,
        quantity: int,
        price: float,
        order_value: float,
        notes: str,
    ) -> Dict[str, Any]:
        current_quantity = int(position["quantity"]) if position else 0
        current_avg_price = float(position["avg_price"]) if position else 0.0
        new_quantity = current_quantity + quantity
        new_avg_price = round(
            ((current_quantity * current_avg_price) + order_value) / new_quantity,
            4,
        )
        self.store.update_cash_balance(round(profile["paper_cash_balance"] - order_value, 2))
        self.store.save_position(
            {
                "symbol": symbol,
                "exchange": exchange,
                "product_type": product_type,
                "quantity": new_quantity,
                "avg_price": new_avg_price,
                "last_price": price,
                "updated_at": utc_now(),
            }
        )
        return self.store.create_order(
            {
                "symbol": symbol,
                "exchange": exchange,
                "product_type": product_type,
                "side": "buy",
                "quantity": quantity,
                "price": price,
                "order_value": order_value,
                "status": "filled",
                "realized_pnl": 0.0,
                "notes": notes,
                "created_at": utc_now(),
            }
        )

    def _execute_sell(
        self,
        profile: Dict[str, Any],
        position: Dict[str, Any],
        symbol: str,
        exchange: str,
        product_type: str,
        quantity: int,
        price: float,
        order_value: float,
        notes: str,
    ) -> Dict[str, Any]:
        current_quantity = int(position["quantity"])
        avg_price = float(position["avg_price"])
        remaining_quantity = current_quantity - quantity
        realized_pnl = round((price - avg_price) * quantity, 2)
        self.store.update_cash_balance(round(profile["paper_cash_balance"] + order_value, 2))
        if remaining_quantity == 0:
            self.store.delete_position(symbol, exchange, product_type)
        else:
            self.store.save_position(
                {
                    "symbol": symbol,
                    "exchange": exchange,
                    "product_type": product_type,
                    "quantity": remaining_quantity,
                    "avg_price": avg_price,
                    "last_price": price,
                    "updated_at": utc_now(),
                }
            )
        return self.store.create_order(
            {
                "symbol": symbol,
                "exchange": exchange,
                "product_type": product_type,
                "side": "sell",
                "quantity": quantity,
                "price": price,
                "order_value": order_value,
                "status": "filled",
                "realized_pnl": realized_pnl,
                "notes": notes,
                "created_at": utc_now(),
            }
        )

    @staticmethod
    def _annotate_positions(positions: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        enriched_positions: List[Dict[str, Any]] = []
        for position in positions:
            mark_price = float(position["last_price"] or position["avg_price"])
            quantity = int(position["quantity"])
            avg_price = float(position["avg_price"])
            market_value = round(mark_price * quantity, 2)
            unrealized_pnl = round((mark_price - avg_price) * quantity, 2)
            enriched_positions.append(
                {
                    **position,
                    "mark_price": round(mark_price, 2),
                    "market_value": market_value,
                    "unrealized_pnl": unrealized_pnl,
                }
            )
        return enriched_positions

    @staticmethod
    def _annotate_alerts(
        alerts: Iterable[Dict[str, Any]],
        watchlist: Iterable[Dict[str, Any]],
        positions: Iterable[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        price_lookup: Dict[Tuple[str, str, str], float] = {}
        for item in list(watchlist) + list(positions):
            if item.get("last_price") is None:
                continue
            key = (
                item["symbol"],
                item["exchange"],
                item.get("product_type", "cash"),
            )
            price_lookup[key] = float(item["last_price"])

        annotated_alerts = []
        for alert in alerts:
            key = (alert["symbol"], alert["exchange"], alert.get("product_type", "cash"))
            latest_price = price_lookup.get(key)
            triggered = False
            if latest_price is not None:
                if alert["trigger_type"] == "above":
                    triggered = latest_price >= float(alert["trigger_price"])
                else:
                    triggered = latest_price <= float(alert["trigger_price"])
            annotated_alerts.append(
                {
                    **alert,
                    "latest_price": latest_price,
                    "triggered": triggered,
                }
            )
        return annotated_alerts

    @staticmethod
    def _required_text(value: Any, label: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise TradingAppError(f"{label} is required.")
        return text

    @classmethod
    def _clean_symbol(cls, value: Any) -> str:
        return cls._required_text(value, "Symbol").upper()

    @classmethod
    def _clean_exchange(cls, value: Any) -> str:
        return cls._required_text(value or "NSE", "Exchange").upper()

    @staticmethod
    def _clean_product_type(value: Any) -> str:
        return str(value or "cash").strip().lower()

    @staticmethod
    def _clean_trigger_type(value: Any) -> str:
        trigger_type = str(value or "").strip().lower()
        if trigger_type not in {"above", "below"}:
            raise TradingAppError("Trigger type must be either 'above' or 'below'.")
        return trigger_type

    @staticmethod
    def _clean_side(value: Any) -> str:
        side = str(value or "").strip().lower()
        if side not in {"buy", "sell"}:
            raise TradingAppError("Order side must be either 'buy' or 'sell'.")
        return side

    @staticmethod
    def _positive_int(value: Any, label: str) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise TradingAppError(f"{label.capitalize()} must be an integer.")
        if number <= 0:
            raise TradingAppError(f"{label.capitalize()} must be greater than zero.")
        return number

    @staticmethod
    def _positive_float(value: Any, label: str) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise TradingAppError(f"{label.capitalize()} must be numeric.")
        if number <= 0:
            raise TradingAppError(f"{label.capitalize()} must be greater than zero.")
        return number
