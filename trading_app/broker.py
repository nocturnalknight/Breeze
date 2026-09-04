from __future__ import annotations

import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from trading_app.settings import AppSettings

ORDER_RATE_LIMIT_PER_SECOND = 10


class BrokerNotConfiguredError(Exception):
    """Raised when the dashboard asks for live data without Breeze credentials."""


class BrokerResponseError(Exception):
    """Raised when Breeze returns an unexpected quote payload."""


class BrokerRateLimitError(Exception):
    """Raised when order-related calls exceed the sliding-window rate limit."""


class BreezeBroker:
    def __init__(self, settings: AppSettings):
        self.settings = settings
        self._client = None

    @property
    def configured(self) -> bool:
        return self.settings.broker_configured

    def get_quote(self, symbol: str, exchange: str, product_type: str = "cash") -> Dict[str, Any]:
        if not self.configured:
            raise BrokerNotConfiguredError(
                "Set BREEZE_API_KEY, BREEZE_API_SECRET, and BREEZE_SESSION_TOKEN before refreshing live quotes."
            )

        client = self._get_client()
        response = client.get_quotes(
            stock_code=symbol,
            exchange_code=exchange,
            product_type=self._normalize_product_type(product_type),
            expiry_date="",
            right="",
            strike_price="",
        )
        price = self._extract_price(response)
        return {
            "symbol": symbol,
            "exchange": exchange,
            "product_type": product_type,
            "price": price,
            "raw": response,
        }

    def _get_client(self):
        if self._client is None:
            from breeze_connect import BreezeConnect

            self._client = BreezeConnect(api_key=self.settings.api_key)
            self._client.generate_session(
                api_secret=self.settings.api_secret,
                session_token=getattr(self, "_session_token_override", None) or self.settings.session_token,
            )
        return self._client

    def refresh_session(self, session_token: str) -> None:
        """Override the session token without mutating the frozen AppSettings."""
        self._session_token_override = session_token
        self._client = None

    def place_order(self, order: Dict[str, Any]) -> Dict[str, Any]:
        if not self.configured:
            raise BrokerNotConfiguredError(
                "Set BREEZE_API_KEY, BREEZE_API_SECRET, and BREEZE_SESSION_TOKEN before placing live orders."
            )
        order_type = str(order.get("order_type", "")).strip().lower()
        if order_type == "market":
            raise ValueError("Market orders are prohibited by SEBI regulation; use 'limit' or 'stoploss'.")
        if order_type not in {"limit", "stoploss"}:
            raise ValueError("order_type must be 'limit' or 'stoploss'.")
        price = float(order.get("price") or 0)
        if price <= 0:
            raise ValueError("price must be greater than zero.")
        validity = str(order.get("validity", "day")).strip().lower()
        if validity not in {"day", "ioc"}:
            raise ValueError("validity must be 'day' or 'ioc'.")
        action = str(order.get("action", "")).strip().lower()
        if action not in {"buy", "sell"}:
            raise ValueError("action must be 'buy' or 'sell'.")
        trigger_price = order.get("trigger_price")
        if order_type == "stoploss" and not trigger_price:
            raise ValueError("trigger_price is required for stoploss orders.")

        self._enforce_rate_limit()
        response = self._get_client().place_order(
            stock_code=order["stock_code"],
            exchange_code=order.get("exchange_code", "NSE"),
            product="cash",
            action=action,
            order_type=order_type,
            stoploss=str(trigger_price) if trigger_price else "",
            quantity=str(order["quantity"]),
            price=str(price),
            validity=validity,
            user_remark="scalper",
        )
        return self._unwrap_dict(response)

    def cancel_order(self, order_id: str, exchange_code: str) -> Dict[str, Any]:
        if not self.configured:
            raise BrokerNotConfiguredError(
                "Set BREEZE_API_KEY, BREEZE_API_SECRET, and BREEZE_SESSION_TOKEN before cancelling orders."
            )
        self._enforce_rate_limit()
        response = self._get_client().cancel_order(exchange_code=exchange_code, order_id=order_id)
        return self._unwrap_dict(response)

    def modify_order(self, order_id: str, exchange_code: str, **kwargs: Any) -> Dict[str, Any]:
        if not self.configured:
            raise BrokerNotConfiguredError(
                "Set BREEZE_API_KEY, BREEZE_API_SECRET, and BREEZE_SESSION_TOKEN before modifying orders."
            )
        order_type = kwargs.get("order_type")
        if order_type is not None and str(order_type).strip().lower() == "market":
            raise ValueError("Market orders are prohibited by SEBI regulation; use 'limit' or 'stoploss'.")

        self._enforce_rate_limit()
        response = self._get_client().modify_order(
            order_id=order_id,
            exchange_code=exchange_code,
            order_type=str(order_type).strip().lower() if order_type else "",
            stoploss=str(kwargs["trigger_price"]) if kwargs.get("trigger_price") else "",
            quantity=str(kwargs["quantity"]) if kwargs.get("quantity") else "",
            price=str(kwargs["price"]) if kwargs.get("price") else "",
            validity=str(kwargs["validity"]).strip().lower() if kwargs.get("validity") else "",
        )
        return self._unwrap_dict(response)

    def square_off(self, position: Dict[str, Any]) -> Dict[str, Any]:
        if not self.configured:
            raise BrokerNotConfiguredError(
                "Set BREEZE_API_KEY, BREEZE_API_SECRET, and BREEZE_SESSION_TOKEN before squaring off positions."
            )
        price = float(position.get("price") or 0)
        if price <= 0:
            raise ValueError("price must be greater than zero to square off (market orders are prohibited).")
        quantity = int(position["quantity"])
        action = "sell" if quantity > 0 else "buy"

        self._enforce_rate_limit()
        response = self._get_client().square_off(
            exchange_code=position.get("exchange_code", "NSE"),
            product="cash",
            stock_code=position["stock_code"],
            action=action,
            order_type="limit",
            validity="day",
            stoploss="0",
            quantity=str(abs(quantity)),
            price=str(price),
            disclosed_quantity="0",
        )
        return self._unwrap_dict(response)

    def get_positions(self) -> List[Dict[str, Any]]:
        if not self.configured:
            raise BrokerNotConfiguredError(
                "Set BREEZE_API_KEY, BREEZE_API_SECRET, and BREEZE_SESSION_TOKEN before fetching positions."
            )
        response = self._get_client().get_portfolio_positions()
        return self._unwrap_list(response)

    def get_orders(self, exchange_code: str) -> List[Dict[str, Any]]:
        if not self.configured:
            raise BrokerNotConfiguredError(
                "Set BREEZE_API_KEY, BREEZE_API_SECRET, and BREEZE_SESSION_TOKEN before fetching orders."
            )
        now = datetime.now(timezone.utc)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        response = self._get_client().get_order_list(
            exchange_code=exchange_code,
            from_date=start_of_day.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            to_date=now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        )
        return self._unwrap_list(response)

    def get_historical_data(
        self,
        stock_code: str,
        exchange_code: str,
        from_date: str,
        to_date: str,
        interval: str,
        product_type: str = "cash",
    ) -> List[Dict[str, Any]]:
        if not self.configured:
            raise BrokerNotConfiguredError(
                "Set BREEZE_API_KEY, BREEZE_API_SECRET, and BREEZE_SESSION_TOKEN before fetching historical data."
            )
        response = self._get_client().get_historical_data_v2(
            interval=interval,
            from_date=from_date,
            to_date=to_date,
            stock_code=stock_code,
            exchange_code=exchange_code,
            product_type=self._normalize_product_type(product_type),
        )
        return self._unwrap_list(response)

    def subscribe_ticks(self, tokens: List[str], exchange_code: str, on_tick: Callable[[Dict[str, Any]], None]) -> None:
        if not self.configured:
            raise BrokerNotConfiguredError(
                "Set BREEZE_API_KEY, BREEZE_API_SECRET, and BREEZE_SESSION_TOKEN before subscribing to ticks."
            )
        client = self._get_client()
        client.on_ticks = on_tick
        client.ws_connect()
        for token in tokens:
            client.subscribe_feeds(stock_token=token)

    def unsubscribe_ticks(self, tokens: List[str], exchange_code: str) -> None:
        client = self._get_client()
        for token in tokens:
            client.unsubscribe_feeds(stock_token=token)

    def _enforce_rate_limit(self) -> None:
        now = time.monotonic()
        window: deque = getattr(self, "_order_call_window", None) or deque()
        while window and now - window[0] > 1.0:
            window.popleft()
        if len(window) >= ORDER_RATE_LIMIT_PER_SECOND:
            raise BrokerRateLimitError(
                f"Order rate limit exceeded: max {ORDER_RATE_LIMIT_PER_SECOND} calls per second."
            )
        window.append(now)
        self._order_call_window = window

    @staticmethod
    def _unwrap_dict(response: Any) -> Dict[str, Any]:
        if isinstance(response, dict):
            error = response.get("Error")
            if error:
                raise BrokerResponseError(str(error))
            success = response.get("Success")
            if isinstance(success, dict):
                return success
            if isinstance(success, list) and success:
                return success[0]
        raise BrokerResponseError("Breeze did not return a valid response.")

    @staticmethod
    def _unwrap_list(response: Any) -> List[Dict[str, Any]]:
        if isinstance(response, dict):
            error = response.get("Error")
            if error:
                raise BrokerResponseError(str(error))
            success = response.get("Success")
            if success is None:
                return []
            if isinstance(success, list):
                return success
            return [success]
        raise BrokerResponseError("Breeze did not return a valid response.")

    @staticmethod
    def _normalize_product_type(product_type: str) -> str:
        normalized = (product_type or "").strip().lower()
        if normalized in {"", "cash", "equity", "spot"}:
            return ""
        return normalized

    @staticmethod
    def _extract_price(response: Dict[str, Any]) -> float:
        payload: Optional[Any] = response.get("Success") if isinstance(response, dict) else None
        if isinstance(payload, list):
            payload = payload[0] if payload else None
        if not isinstance(payload, dict):
            raise BrokerResponseError("Breeze did not return a quote payload in the expected format.")

        candidate_keys = (
            "ltp",
            "LTP",
            "last",
            "Last",
            "last_price",
            "LastPrice",
            "close",
            "Close",
            "stock_price",
        )
        for key in candidate_keys:
            value = payload.get(key)
            if value in (None, ""):
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        raise BrokerResponseError("Unable to extract a numeric quote price from the Breeze response.")
