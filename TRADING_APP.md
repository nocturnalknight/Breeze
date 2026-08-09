# Personalized Trading App

This repo now includes a phase-1 trading desk scaffold on top of `breeze_connect`.

## What it does

- Stores a personalized profile with your exchange preference, default size, max open positions, max position value, and max drawdown limit.
- Maintains a watchlist with manual prices or live Breeze quote refresh when credentials are configured.
- Tracks price alerts per instrument.
- Executes paper trades into a local SQLite ledger so you can test workflows before enabling any live order path.
- Serves a single-screen dashboard for overview, watchlist, alerts, positions, and recent orders.

## Quick start

1. Create or activate a Python environment.
2. Install the app dependencies:

```bash
pip install -r requirements-trading-app.txt
```

3. Optionally export the variables from `.env.example`.
4. Start the app:

```bash
uvicorn trading_app.main:app --reload
```

5. Open `http://127.0.0.1:8000`.

## Live Breeze quotes

If you set `BREEZE_API_KEY`, `BREEZE_API_SECRET`, and `BREEZE_SESSION_TOKEN`, the `Refresh Quotes` actions use Breeze for live prices. The scaffold still keeps order execution in paper mode.

## Project layout

- `trading_app/main.py`: FastAPI routes and HTML entrypoint
- `trading_app/service.py`: portfolio, risk, alerts, and paper-trading logic
- `trading_app/storage.py`: SQLite schema and persistence
- `trading_app/broker.py`: lazy Breeze adapter for live quote refresh
- `trading_app/templates/` and `trading_app/static/`: dashboard UI

## Next phases

- Add instrument search through Breeze `get_names()`
- Add strategy templates and journaling
- Add historical charts and replay/backtest views
- Add broker-backed order routing behind an explicit enable switch
