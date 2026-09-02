import asyncio
import sys
from types import SimpleNamespace

import pytest

from openbb_choice.models.equity_quote import ChoiceEquityQuoteFetcher


class FakeQuoteAPI:
    def __init__(self):
        self.snapshot_calls = []
        self.stopped = False

    def start(self, options):
        return SimpleNamespace(ErrorCode=0, ErrorMsg="success")

    def stop(self):
        self.stopped = True
        return SimpleNamespace(ErrorCode=0, ErrorMsg="success")

    def csqsnapshot(self, symbols, indicators, options):
        self.snapshot_calls.append((symbols, indicators, options))
        names = indicators.split(",")
        return SimpleNamespace(
            ErrorCode=0,
            ErrorMsg="success",
            Indicators=names,
            Data={
                "000001.SZ": ["14:21:55", 10.0, 10.1, 10.6, 9.9, 10.4, 123, 789],
                "600519.SH": ["14:21:56", 1500, 1501, 1520, 1490, 1510, 456, 987],
            },
        )


def test_equity_quote_fetcher_maps_snapshot(monkeypatch):
    fake = FakeQuoteAPI()
    monkeypatch.setitem(sys.modules, "EmQuantAPI", SimpleNamespace(c=fake))
    monkeypatch.setenv("CHOICE_LOGIN_MODE", "password")
    monkeypatch.setenv("CHOICE_VOLUME_MULTIPLIER", "100")

    results = asyncio.run(
        ChoiceEquityQuoteFetcher.fetch_data(
            {"symbol": "000001.SZ,600519.SH", "use_cache": False},
            {"choice_username": "demo", "choice_password": "secret"},
        )
    )

    assert len(results) == 2
    assert results[0].symbol == "000001.SZ"
    assert results[0].last_price == 10.4
    assert results[0].prev_close == 10.0
    assert results[0].change == pytest.approx(0.4)
    assert results[0].change_percent == pytest.approx(0.04)
    assert results[0].volume == 12300
    assert results[0].amount == 789
    assert results[0].quote_time.tzinfo is not None
    assert results[0].source == "choice"
    assert fake.snapshot_calls[0][0] == "000001.SZ,600519.SH"
    assert fake.stopped is True
