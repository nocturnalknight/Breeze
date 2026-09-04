from __future__ import annotations

import logging
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from trading_app.api_models import (
    AlertCreateRequest,
    LiveOrderModifyRequest,
    LiveOrderRequest,
    PaperOrderRequest,
    PriceUpdateRequest,
    ProfileUpdateRequest,
    SessionRefreshRequest,
    SquareOffRequest,
    WatchlistCreateRequest,
)
from trading_app.broker import (
    BrokerNotConfiguredError,
    BrokerRateLimitError,
    BrokerResponseError,
    BreezeBroker,
)
from trading_app.service import TradingAppError, TradingAppService
from trading_app.settings import AppSettings
from trading_app.storage import TradingAppStore
from trading_app.udf.router import configure as configure_udf
from trading_app.udf.router import udf_router
from trading_app.udf.security_master import security_master
from trading_app.ws.tick_bridge import configure as configure_ws
from trading_app.ws.tick_bridge import router as ws_router


logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
settings = AppSettings.from_env()
store = TradingAppStore(settings)
store.initialize()
broker = BreezeBroker(settings)
service = TradingAppService(store, broker)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")

configure_udf(broker)
configure_ws(broker)

app = FastAPI(
    title=settings.title,
    version="0.1.0",
    description="Personalized trading dashboard with watchlists, alerts, and paper trading.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.include_router(udf_router)
app.include_router(ws_router)


def _model_dump(model):
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_unset=True)
    return model.dict(exclude_unset=True)


@app.exception_handler(TradingAppError)
def trading_app_error_handler(_: Request, exc: TradingAppError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(BrokerNotConfiguredError)
def broker_not_configured_handler(_: Request, exc: BrokerNotConfiguredError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(BrokerResponseError)
def broker_response_error_handler(_: Request, exc: BrokerResponseError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(BrokerRateLimitError)
def rate_limit_handler(_: Request, exc: BrokerRateLimitError) -> JSONResponse:
    return JSONResponse(status_code=429, content={"detail": str(exc)})


@app.exception_handler(ValueError)
def value_error_handler(_: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.on_event("startup")
def on_startup() -> None:
    security_master.ensure_loaded()
    scheduler.add_job(security_master.refresh, "cron", hour=8, minute=5, id="security_master_refresh")
    scheduler.add_job(_warn_session_expiry, "cron", hour=23, minute=55, id="session_expiry_warning")
    scheduler.start()


@app.on_event("shutdown")
def on_shutdown() -> None:
    scheduler.shutdown(wait=False)


def _warn_session_expiry() -> None:
    logger.warning(
        "Breeze session token expires at midnight IST. Use the Refresh Session button to renew."
    )


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "app_title": settings.title,
            "broker_configured": service.broker_configured,
        },
    )


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "broker_configured": service.broker_configured}


@app.get("/api/dashboard")
def dashboard() -> dict:
    return service.get_dashboard()


@app.put("/api/profile")
def update_profile(payload: ProfileUpdateRequest) -> dict:
    return service.update_profile(_model_dump(payload))


@app.post("/api/watchlist")
def create_watchlist_item(payload: WatchlistCreateRequest) -> dict:
    return service.add_watchlist_item(_model_dump(payload))


@app.delete("/api/watchlist/{item_id}")
def delete_watchlist_item(item_id: int) -> dict:
    service.remove_watchlist_item(item_id)
    return {"deleted": True}


@app.post("/api/watchlist/{item_id}/price")
def update_watchlist_price(item_id: int, payload: PriceUpdateRequest) -> dict:
    return service.update_watchlist_price(item_id, payload.price)


@app.post("/api/watchlist/{item_id}/refresh")
def refresh_watchlist_item(item_id: int) -> dict:
    return service.refresh_watchlist_item(item_id)


@app.post("/api/watchlist/refresh")
def refresh_watchlist() -> dict:
    return {"items": service.refresh_watchlist()}


@app.post("/api/alerts")
def create_alert(payload: AlertCreateRequest) -> dict:
    return service.add_alert(_model_dump(payload))


@app.delete("/api/alerts/{alert_id}")
def delete_alert(alert_id: int) -> dict:
    service.remove_alert(alert_id)
    return {"deleted": True}


@app.post("/api/paper/orders")
def create_paper_order(payload: PaperOrderRequest) -> dict:
    return service.place_paper_order(_model_dump(payload))


@app.post("/api/paper/reset")
def reset_paper_account() -> dict:
    return service.reset_paper_account()


@app.post("/api/live/orders")
def place_live_order(payload: LiveOrderRequest) -> dict:
    order = {
        "stock_code": payload.symbol.upper(),
        "exchange_code": payload.exchange.upper(),
        "action": payload.side,
        "order_type": payload.order_type,
        "quantity": payload.quantity,
        "price": payload.price,
        "trigger_price": payload.trigger_price,
        "validity": payload.validity,
    }
    return broker.place_order(order)


@app.get("/api/live/orders")
def list_live_orders(exchange: str = "NSE") -> dict:
    return {"orders": broker.get_orders(exchange.upper())}


@app.delete("/api/live/orders/{order_id}")
def cancel_live_order(order_id: str, exchange: str = "NSE") -> dict:
    return broker.cancel_order(order_id, exchange.upper())


@app.put("/api/live/orders/{order_id}")
def modify_live_order(order_id: str, payload: LiveOrderModifyRequest) -> dict:
    updates = _model_dump(payload)
    exchange = updates.pop("exchange", "NSE").upper()
    return broker.modify_order(order_id, exchange, **updates)


@app.post("/api/live/squareoff")
def square_off_position(payload: SquareOffRequest) -> dict:
    position = {
        "stock_code": payload.symbol.upper(),
        "exchange_code": payload.exchange.upper(),
        "quantity": payload.quantity,
        "price": payload.price,
    }
    return broker.square_off(position)


@app.get("/api/live/positions")
def list_live_positions() -> dict:
    return {"positions": broker.get_positions()}


@app.post("/auth/refresh")
def refresh_session(payload: SessionRefreshRequest) -> dict:
    broker.refresh_session(payload.session_token)
    return {"status": "refreshed"}


def run() -> None:
    import uvicorn

    uvicorn.run(
        "trading_app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    run()
