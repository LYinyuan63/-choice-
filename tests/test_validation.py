import json
import sys
from datetime import date
from types import SimpleNamespace

from qianji_data_mini.adapters.choice import ChoiceAdapter
from qianji_data_mini.db import Database
from qianji_data_mini.ingest import ingest_daily
from qianji_data_mini.openbb_provider.equity_historical import (
    QianjiEquityHistoricalFetcher,
)
from qianji_data_mini.validation import _safe_message, run_validation


class FakeChoiceSDK:
    def __init__(self):
        self.start_options = None
        self.stopped = False

    def start(self, options):
        self.start_options = options
        return SimpleNamespace(ErrorCode=0, ErrorMsg="success")

    def stop(self):
        self.stopped = True
        return SimpleNamespace(ErrorCode=0, ErrorMsg="success")

    def csd(self, symbol, indicators, start_date, end_date, options):
        del start_date, end_date, options
        names = indicators.split(",")
        values = [
            [10.75, 10.80],
            [10.88, 11.00],
            [10.72, 10.74],
            [10.78, 10.98],
            [107_549_901, 156_730_393],
            [1_163_189_278.51, 1_713_460_189.52],
            [10.77, 10.78],
            [0.0929, 1.8553],
        ]
        return SimpleNamespace(
            ErrorCode=0,
            ErrorMsg="success",
            Codes=[symbol],
            Dates=["2026/7/17", "2026/07/20"],
            Indicators=names,
            Data={symbol: values},
        )


def test_choice_password_options(monkeypatch):
    monkeypatch.setenv("CHOICE_LOGIN_MODE", "password")
    monkeypatch.setenv("CHOICE_USERNAME", "demo_user")
    monkeypatch.setenv("CHOICE_PASSWORD", "demo_password")
    monkeypatch.setenv("CHOICE_START_OPTIONS", "ForceLogin=0")
    options = ChoiceAdapter._login_options()
    assert "UserName=demo_user" in options
    assert "PassWord=demo_password" in options
    assert "ForceLogin=0" in options


def test_choice_userinfo_does_not_include_credentials(monkeypatch):
    monkeypatch.setenv("CHOICE_LOGIN_MODE", "userinfo")
    monkeypatch.setenv("CHOICE_USERNAME", "demo_user")
    monkeypatch.setenv("CHOICE_PASSWORD", "demo_password")
    monkeypatch.setenv("CHOICE_START_OPTIONS", "ForceLogin=0")
    options = ChoiceAdapter._login_options()
    assert options == "ForceLogin=0"


def test_choice_real_response_shape_can_be_ingested_idempotently(
    monkeypatch, tmp_path
):
    fake = FakeChoiceSDK()
    monkeypatch.setitem(sys.modules, "EmQuantAPI", SimpleNamespace(c=fake))
    monkeypatch.setenv("CHOICE_LOGIN_MODE", "userinfo")
    monkeypatch.setenv("CHOICE_START_OPTIONS", "ForceLogin=0")
    database_path = tmp_path / "choice.db"

    first = ingest_daily(
        source="choice",
        symbols=["000001.SZ"],
        start_date="2026-07-17",
        end_date="2026-07-20",
        database_path=database_path,
    )
    second = ingest_daily(
        source="choice",
        symbols=["000001.SZ"],
        start_date="2026-07-17",
        end_date="2026-07-20",
        database_path=database_path,
    )

    rows = Database(database_path).query_daily(
        symbol="000001.SZ",
        source="choice",
        start_date="2026-07-17",
        end_date="2026-07-20",
    )
    assert first.failed_symbols == {}
    assert second.failed_symbols == {}
    assert first.received_rows == 2
    assert len(rows) == 2
    assert rows[0]["date"] == "2026-07-17"
    assert rows[0]["change_percent"] == 0.0929
    assert fake.start_options == "ForceLogin=0"
    assert fake.stopped is True


def test_qianji_provider_normalizes_stored_percentage_points():
    results = QianjiEquityHistoricalFetcher.transform_data(
        query=None,
        data=[
            {
                "date": "2026-08-31",
                "symbol": "000001.SZ",
                "open": 11.64,
                "high": 11.77,
                "low": 11.62,
                "close": 11.72,
                "volume": 90_885_655,
                "change_percent": 0.6009,
                "source": "choice",
            }
        ],
    )
    assert results[0].change_percent == 0.006009


def test_mock_validation_exports_evidence(tmp_path):
    evidence = run_validation(
        sources=["mock"],
        symbols=["000001.SZ", "600000.SH"],
        start_date=date(2026, 8, 3),
        end_date=date(2026, 8, 7),
        database_path=tmp_path / "market.db",
        output_dir=tmp_path / "evidence",
    )
    assert evidence["results"][0]["status"] == "PASS"
    assert evidence["results"][0]["received_rows"] == 10
    assert (tmp_path / "evidence" / "真实数据验证证据.xlsx").exists()
    json_path = tmp_path / "evidence" / "真实数据验证结果.json"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["credentials_included"] is False


def test_error_messages_redact_credentials(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "private-token")
    monkeypatch.setenv("CHOICE_USERNAME", "private-user")
    monkeypatch.setenv("CHOICE_PASSWORD", "private-password")
    safe = _safe_message("private-user private-password private-token")
    assert safe == "*** *** ***"
