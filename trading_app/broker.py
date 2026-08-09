from __future__ import annotations

from typing import Any, Dict, Optional

from trading_app.settings import AppSettings


class BrokerNotConfiguredError(Exception):
    """Raised when the dashboard asks for live data without Breeze credentials."""


class BrokerResponseError(Exception):
    """Raised when Breeze returns an unexpected quote payload."""


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
                session_token=self.settings.session_token,
            )
        return self._client

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
