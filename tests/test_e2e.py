from datetime import date

import pandas as pd
from fastapi.testclient import TestClient

from qianji_data_mini.db import Database
from qianji_data_mini.ingest import ingest_daily
from qianji_data_mini.service import create_app
from qianji_data_mini.adapters.tushare import TushareAdapter


def test_mock_ingest_is_idempotent(tmp_path):
    database_path = tmp_path / "market.db"
    first = ingest_daily(
        source="mock",
        symbols=["000001.SZ", "600000.SH"],
        start_date=date(2026, 8, 3),
        end_date=date(2026, 8, 7),
        database_path=database_path,
    )
    second = ingest_daily(
        source="mock",
        symbols=["000001.SZ", "600000.SH"],
        start_date=date(2026, 8, 3),
        end_date=date(2026, 8, 7),
        database_path=database_path,
    )
    assert first.failed_symbols == {}
    assert first.received_rows == 10
    assert second.received_rows == 10
    database = Database(database_path)
    assert len(database.query_daily("000001.SZ", source="mock")) == 5
    assert len(database.query_daily("600000.SH", source="mock")) == 5


def test_rest_simulated_client(tmp_path):
    database_path = tmp_path / "market.db"
    ingest_daily(
        source="mock",
        symbols="000001.SZ",
        start_date="2026-08-03",
        end_date="2026-08-07",
        database_path=database_path,
    )
    client = TestClient(create_app(database_path))
    response = client.get(
        "/v1/equity/price/historical",
        params={"symbol": "000001.SZ", "source": "auto"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "qianji"
    assert payload["count"] == 5
    assert payload["results"][0]["source"] == "mock"


def test_tushare_units_are_normalized():
    class StubAPI:
        @staticmethod
        def daily(**kwargs):
            return pd.DataFrame([
                {
                    "ts_code": "000001.SZ", "trade_date": "20260828",
                    "open": 10.0, "high": 10.5, "low": 9.9, "close": 10.4,
                    "vol": 123.45, "amount": 678.9, "pre_close": 10.0,
                    "pct_chg": 4.0,
                }
            ])

    adapter = TushareAdapter.__new__(TushareAdapter)
    adapter.api = StubAPI()
    rows = adapter.fetch_daily("000001.SZ", date(2026, 8, 28), date(2026, 8, 28))
    assert rows[0].date == date(2026, 8, 28)
    assert rows[0].volume == 12345
    assert rows[0].amount == 678900
    assert rows[0].volume_unit == "share"
