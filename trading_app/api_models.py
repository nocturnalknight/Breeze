from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class ProfileUpdateRequest(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=80)
    trading_style: Optional[str] = Field(default=None, max_length=80)
    preferred_exchange: Optional[str] = Field(default=None, max_length=12)
    max_open_positions: Optional[int] = Field(default=None, gt=0)
    max_position_value: Optional[float] = Field(default=None, gt=0)
    max_drawdown_limit: Optional[float] = Field(default=None, gt=0)
    default_order_quantity: Optional[int] = Field(default=None, gt=0)
    paper_starting_cash: Optional[float] = Field(default=None, gt=0)
    notes: Optional[str] = Field(default=None, max_length=2000)


class WatchlistCreateRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=40)
    exchange: str = Field(default="NSE", min_length=1, max_length=12)
    product_type: str = Field(default="cash", min_length=1, max_length=20)
    notes: str = Field(default="", max_length=500)


class PriceUpdateRequest(BaseModel):
    price: float = Field(gt=0)


class AlertCreateRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=40)
    exchange: str = Field(default="NSE", min_length=1, max_length=12)
    product_type: str = Field(default="cash", min_length=1, max_length=20)
    trigger_type: Literal["above", "below"]
    trigger_price: float = Field(gt=0)
    note: str = Field(default="", max_length=500)


class PaperOrderRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=40)
    exchange: str = Field(default="NSE", min_length=1, max_length=12)
    product_type: str = Field(default="cash", min_length=1, max_length=20)
    side: Literal["buy", "sell"]
    quantity: int = Field(gt=0)
    price: float = Field(gt=0)
    notes: str = Field(default="", max_length=500)
