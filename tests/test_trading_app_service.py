import tempfile
import unittest
from pathlib import Path

from trading_app.broker import BreezeBroker
from trading_app.service import TradingAppError, TradingAppService
from trading_app.settings import AppSettings
from trading_app.storage import TradingAppStore


class TradingAppServiceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.settings = AppSettings(
            title="Test Desk",
            host="127.0.0.1",
            port=8000,
            db_path=Path(self.tempdir.name) / "trading.sqlite3",
            default_cash=100000.0,
            api_key=None,
            api_secret=None,
            session_token=None,
        )
        self.store = TradingAppStore(self.settings)
        self.store.initialize()
        self.service = TradingAppService(self.store, BreezeBroker(self.settings))

    def tearDown(self):
        self.tempdir.cleanup()

    def test_buy_order_updates_cash_and_position(self):
        result = self.service.place_paper_order(
            {
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "product_type": "cash",
                "side": "buy",
                "quantity": 10,
                "price": 100.0,
                "notes": "Breakout test",
            }
        )

        self.assertEqual(result["portfolio"]["cash_balance"], 99000.0)
        self.assertEqual(len(result["portfolio"]["positions"]), 1)
        self.assertEqual(result["portfolio"]["positions"][0]["quantity"], 10)
        self.assertEqual(result["portfolio"]["positions"][0]["avg_price"], 100.0)

    def test_cannot_sell_more_than_available_quantity(self):
        self.service.place_paper_order(
            {
                "symbol": "INFY",
                "exchange": "NSE",
                "product_type": "cash",
                "side": "buy",
                "quantity": 2,
                "price": 1500.0,
                "notes": "",
            }
        )

        with self.assertRaises(TradingAppError):
            self.service.place_paper_order(
                {
                    "symbol": "INFY",
                    "exchange": "NSE",
                    "product_type": "cash",
                    "side": "sell",
                    "quantity": 3,
                    "price": 1510.0,
                    "notes": "",
                }
            )

    def test_manual_price_update_marks_position_to_market(self):
        self.service.place_paper_order(
            {
                "symbol": "TCS",
                "exchange": "NSE",
                "product_type": "cash",
                "side": "buy",
                "quantity": 5,
                "price": 100.0,
                "notes": "",
            }
        )
        watch_item_id = self.store.list_watchlist()[0]["id"]

        self.service.update_watchlist_price(watch_item_id, 120.0)
        snapshot = self.service.get_portfolio_snapshot()

        self.assertEqual(snapshot["positions"][0]["mark_price"], 120.0)
        self.assertEqual(snapshot["total_unrealized_pnl"], 100.0)


if __name__ == "__main__":
    unittest.main()
