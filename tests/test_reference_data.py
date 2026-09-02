import sys
from datetime import date
from types import SimpleNamespace

from qianji_data_mini import Database, ingest_choice_reference
from qianji_data_mini.adapters.choice import ChoiceAdapter


class FakeChoiceReferenceSDK:
    def __init__(self):
        self.start_calls = 0
        self.stop_calls = 0
        self.css_calls = []
        self.tradedates_calls = []

    def start(self, options):
        del options
        self.start_calls += 1
        return SimpleNamespace(ErrorCode=0, ErrorMsg="success")

    def stop(self):
        self.stop_calls += 1
        return SimpleNamespace(ErrorCode=0, ErrorMsg="success")

    def css(self, codes, indicators, options):
        del options
        self.css_calls.append((codes, indicators))
        if indicators == "BAD":
            return SimpleNamespace(ErrorCode=1001, ErrorMsg="invalid indicator")
        names = indicators.split(",")
        master = {
            "000001.SZ": {"NAME": "平安银行", "LISTDATE": "1991/4/3"},
            "601988.SH": {"NAME": "中国银行", "LISTDATE": "2006-07-05"},
            "510300.SH": {"NAME": "沪深300ETF", "LISTDATE": "2012-05-28"},
        }
        return SimpleNamespace(
            ErrorCode=0,
            ErrorMsg="success",
            Codes=codes.split(","),
            Indicators=names,
            Data={
                code: [master[code].get(name) for name in names]
                for code in codes.split(",")
            },
        )

    def tradedates(self, start_date, end_date, options):
        self.tradedates_calls.append((start_date, end_date, options))
        return SimpleNamespace(
            ErrorCode=0,
            ErrorMsg="success",
            Data=[
                "2026/08/24",
                "2026/08/25",
                "2026/08/26",
                "2026/08/27",
                "2026/08/28",
            ],
        )

    def sector(self, sector_code, as_of_date):
        del as_of_date
        assert sector_code == "001004"
        return SimpleNamespace(
            ErrorCode=0,
            ErrorMsg="success",
            Data=["000001.SZ", "601988.SH", "510300.SH", "invalid"],
        )


def test_choice_reference_data_is_ingested_idempotently(monkeypatch, tmp_path):
    fake = FakeChoiceReferenceSDK()
    monkeypatch.setitem(sys.modules, "EmQuantAPI", SimpleNamespace(c=fake))
    monkeypatch.setenv("CHOICE_LOGIN_MODE", "userinfo")
    monkeypatch.setenv("CHOICE_START_OPTIONS", "ForceLogin=0")
    monkeypatch.setenv("CHOICE_MASTER_INDICATORS", "BAD")
    database_path = tmp_path / "reference.db"

    kwargs = {
        "symbols": ["000001.SZ", "601988.SH", "510300.SH"],
        "calendar_start_date": "2026-08-24",
        "calendar_end_date": "2026-08-30",
        "markets": ["CNSESH", "CNSESZ"],
        "as_of_date": "2026-08-30",
        "database_path": database_path,
    }
    first = ingest_choice_reference(**kwargs)
    second = ingest_choice_reference(**kwargs)

    database = Database(database_path)
    master = database.query_security_master(
        source="choice",
        symbols=kwargs["symbols"],
    )
    sh_calendar = database.query_trading_calendar(
        source="choice",
        market="CNSESH",
        start_date="2026-08-24",
        end_date="2026-08-30",
    )
    sz_calendar = database.query_trading_calendar(
        source="choice",
        market="CNSESZ",
        start_date="2026-08-24",
        end_date="2026-08-30",
    )

    assert first.errors == {}
    assert second.errors == {}
    assert first.security_received_rows == 3
    assert first.calendar_received_rows == 14
    assert len(master) == 3
    assert set(master["name"]) == {"平安银行", "中国银行", "沪深300ETF"}
    assert master.loc[master["symbol"] == "510300.SH", "asset_type"].item() == "etf"
    assert len(sh_calendar) == len(sz_calendar) == 7
    assert int(sh_calendar["is_open"].sum()) == 5
    assert int(sz_calendar["is_open"].sum()) == 5
    assert fake.stop_calls == 2
    assert any(indicators == "BAD" for _, indicators in fake.css_calls)
    assert any(indicators == "NAME,LISTDATE" for _, indicators in fake.css_calls)

    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM security_master").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM trading_calendar").fetchone()[0] == 14
        assert connection.execute("SELECT COUNT(*) FROM reference_ingestion_run").fetchone()[0] == 4


def test_choice_all_a_sector_symbols_are_normalized(monkeypatch):
    fake = FakeChoiceReferenceSDK()
    monkeypatch.setitem(sys.modules, "EmQuantAPI", SimpleNamespace(c=fake))
    monkeypatch.setenv("CHOICE_LOGIN_MODE", "userinfo")
    adapter = ChoiceAdapter()
    try:
        symbols = adapter.fetch_sector_symbols(
            sector_code="001004",
            as_of_date=date(2026, 8, 30),
        )
    finally:
        adapter.close()
    assert symbols == ["000001.SZ", "601988.SH", "510300.SH"]
