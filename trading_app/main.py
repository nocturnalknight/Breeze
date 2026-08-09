from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from trading_app.api_models import (
    AlertCreateRequest,
    PaperOrderRequest,
    PriceUpdateRequest,
    ProfileUpdateRequest,
    WatchlistCreateRequest,
)
from trading_app.broker import BrokerNotConfiguredError, BrokerResponseError, BreezeBroker
from trading_app.service import TradingAppError, TradingAppService
from trading_app.settings import AppSettings
from trading_app.storage import TradingAppStore


BASE_DIR = Path(__file__).resolve().parent
settings = AppSettings.from_env()
store = TradingAppStore(settings)
store.initialize()
broker = BreezeBroker(settings)
service = TradingAppService(store, broker)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(
    title=settings.title,
    version="0.1.0",
    description="Personalized trading dashboard with watchlists, alerts, and paper trading.",
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


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
