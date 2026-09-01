import asyncio
import sys
from datetime import date
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from openbb_choice.models.equity_historical import (
    ChoiceEquityHistoricalFetcher,
    ChoiceEquityHistoricalQueryParams,
)
from openbb_choice.utils.emquant import (
    ChoiceAuthenticationError,
    ChoiceClient,
    ChoiceEmptyRecordWarning,
    ChoiceSDKError,
    _iso_date,
    build_login_options,
)


class FakeEmQuantAPI:
    def __init__(self):
        self.start_options = None
        self.csd_calls = []
        self.stopped = False

    def start(self, options):
        self.start_options = options
        return SimpleNamespace(ErrorCode=0, ErrorMsg="success")

    def stop(self):
        self.stopped = True
        return SimpleNamespace(ErrorCode=0, ErrorMsg="success")

    def csd(self, symbol, indicators, start_date, end_date, options):
        self.csd_calls.append((symbol, indicators, start_date, end_date, options))
        names = indicators.split(",")
        values = [
            [10.0, 10.2],
            [10.5, 10.4],
            [9.9, 10.1],
            [10.4, 10.3],
            [123.0, 456.0],
            [789.0, 987.0],
            [10.0, 10.4],
            [4.0, -0.961538],
        ]
        return SimpleNamespace(
            ErrorCode=0,
            ErrorMsg="success",
            Codes=[symbol],
            Dates=["2026/8/3", "2026/08/04"],
            Indicators=names,
            Data={symbol: values},
        )


def test_query_normalizes_symbols_and_rejects_bad_dates():
    query = ChoiceEquityHistoricalQueryParams(
        symbol="600036.SS, 000001.SZ,600036.SH",
        start_date="2026-08-01",
        end_date="2026-08-31",
    )
    assert query.symbol == "600036.SH,000001.SZ"

    with pytest.raises(ValidationError):
        ChoiceEquityHistoricalQueryParams(
            symbol="000001.SZ",
            start_date="20260801",
            end_date="2026-08-31",
        )


def test_force_login_is_blocked(monkeypatch):
    monkeypatch.setenv("CHOICE_START_OPTIONS", "ForceLogin=1")
    monkeypatch.delenv("CHOICE_ALLOW_FORCE_LOGIN", raising=False)
    with pytest.raises(ChoiceAuthenticationError):
        build_login_options(
            {"choice_username": "demo", "choice_password": "secret"}
        )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026/7/17", "2026-07-17"),
        ("2026/07/17 00:00:00", "2026-07-17"),
        ("2026-7-17", "2026-07-17"),
        ("2026-07-17", "2026-07-17"),
        ("20260717", "2026-07-17"),
        (date(2026, 7, 17), "2026-07-17"),
    ],
)
def test_choice_response_dates_are_normalized(raw, expected):
    assert _iso_date(raw) == expected


def test_invalid_choice_response_date_is_handled():
    with pytest.raises(ChoiceSDKError, match="Invalid Choice response date"):
        _iso_date("2026/2/30")


def test_fetcher_matches_openbb_shape(monkeypatch):
    fake = FakeEmQuantAPI()
    monkeypatch.setitem(sys.modules, "EmQuantAPI", SimpleNamespace(c=fake))
    monkeypatch.setenv("CHOICE_LOGIN_MODE", "password")
    monkeypatch.setenv("CHOICE_START_OPTIONS", "ForceLogin=0")
    monkeypatch.setenv("CHOICE_VOLUME_MULTIPLIER", "100")
    monkeypatch.setenv("CHOICE_AMOUNT_MULTIPLIER", "1")

    results = asyncio.run(
        ChoiceEquityHistoricalFetcher.fetch_data(
            {
                "symbol": "000001.SZ",
                "start_date": date(2026, 8, 1),
                "end_date": date(2026, 8, 31),
                "period": "weekly",
                "adjustment": "qfq",
                "use_cache": False,
            },
            {
                "choice_username": "demo_user",
                "choice_password": "demo_password",
            },
        )
    )

    assert len(results) == 2
    assert results[0].symbol == "000001.SZ"
    assert results[0].date == date(2026, 8, 3)
    assert results[0].volume == 12300
    assert results[0].amount == 789
    assert results[0].prev_close == 10.0
    assert results[0].change == pytest.approx(0.4)
    assert results[0].change_percent == pytest.approx(0.04)
    assert results[0].source == "choice"
    assert "Period=2" in fake.csd_calls[0][-1]
    assert "AdjustFlag=3" in fake.csd_calls[0][-1]
    assert "UserName=demo_user" in fake.start_options
    assert "PassWord=demo_password" in fake.start_options
    assert fake.stopped is True


class FakePlaceholderAPI:
    def __init__(self, values):
        self.values = values

    def csd(self, symbol, indicators, start_date, end_date, options):
        return SimpleNamespace(
            ErrorCode=0,
            ErrorMsg="success",
            Codes=[symbol],
            Dates=["2026/7/31", "2026/8/31"],
            Indicators=indicators.split(","),
            Data={symbol: self.values},
        )


def test_historical_skips_all_empty_ohlc_placeholder():
    values = [
        [10.0, None],
        [10.5, None],
        [9.9, None],
        [10.4, None],
        [123.0, None],
        [789.0, None],
        [10.0, None],
        [4.0, None],
    ]
    client = ChoiceClient()
    client.api = FakePlaceholderAPI(values)

    with pytest.warns(
        ChoiceEmptyRecordWarning,
        match=r"symbol=000001\.SZ, date=2026-08-31, period=monthly",
    ):
        records = client.historical(
            symbols=["000001.SZ"],
            start_date=date(2026, 7, 1),
            end_date=date(2026, 8, 31),
            period="monthly",
        )

    assert len(records) == 1
    assert records[0]["date"] == "2026-07-31"
    assert records[0]["close"] == 10.4


def test_historical_rejects_partly_empty_ohlc():
    values = [
        [10.0, None],
        [10.5, 10.6],
        [9.9, 10.1],
        [10.4, 10.5],
        [123.0, 456.0],
        [789.0, 987.0],
        [10.0, 10.4],
        [4.0, 0.961538],
    ]
    client = ChoiceClient()
    client.api = FakePlaceholderAPI(values)

    with pytest.raises(
        ChoiceSDKError,
        match=r"incomplete OHLC .*date=2026-08-31.*missing=OPEN",
    ):
        client.historical(
            symbols=["000001.SZ"],
            start_date=date(2026, 7, 1),
            end_date=date(2026, 8, 31),
            period="monthly",
        )
