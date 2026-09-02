import sys
from datetime import date
from types import SimpleNamespace

from qianji_data_mini import Database, refresh_choice_reference
from qianji_data_mini.models import SecurityMaster


class FakeChoiceRefreshSDK:
    def __init__(self):
        self.start_calls = 0
        self.stop_calls = 0

    def start(self, options):
        del options
        self.start_calls += 1
        return SimpleNamespace(ErrorCode=0, ErrorMsg="success")

    def stop(self):
        self.stop_calls += 1
        return SimpleNamespace(ErrorCode=0, ErrorMsg="success")

    def sector(self, sector_code, as_of_date):
        del as_of_date
        assert sector_code == "001004"
        return SimpleNamespace(
            ErrorCode=0,
            ErrorMsg="success",
            Data=["000001.SZ", "300001.SZ"],
        )

    def css(self, codes, indicators, options):
        del options
        names = indicators.split(",")
        master = {
            "000001.SZ": {
                "NAME": "平安银行",
                "LISTDATE": "1991/4/3",
                "DELISTDATE": None,
            },
            "300001.SZ": {
                "NAME": "特锐德",
                "LISTDATE": "2009-10-30",
                "DELISTDATE": None,
            },
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
        del start_date, end_date, options
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


def _seed_previous_master(database: Database) -> None:
    database.upsert_security_master(
        [
            SecurityMaster(
                symbol="000001.SZ",
                name="平安银行股份",
                exchange="SZSE",
                asset_type="equity",
                list_date=date(1991, 4, 3),
                status="active",
                as_of_date=date(2026, 8, 30),
            ),
            SecurityMaster(
                symbol="601988.SH",
                name="中国银行",
                exchange="SSE",
                asset_type="equity",
                list_date=date(2006, 7, 5),
                status="active",
                as_of_date=date(2026, 8, 30),
            ),
        ]
    )


def test_choice_reference_refresh_tracks_changes_and_is_idempotent(
    monkeypatch, tmp_path
):
    fake = FakeChoiceRefreshSDK()
    monkeypatch.setitem(sys.modules, "EmQuantAPI", SimpleNamespace(c=fake))
    monkeypatch.setenv("CHOICE_LOGIN_MODE", "userinfo")
    database_path = tmp_path / "refresh.db"
    database = Database(database_path)
    _seed_previous_master(database)

    kwargs = {
        "snapshot_date": "2026-08-31",
        "calendar_start_date": "2026-08-24",
        "calendar_end_date": "2026-08-30",
        "markets": ["CNSESH", "CNSESZ"],
        "database_path": database_path,
    }
    first = refresh_choice_reference(**kwargs)
    second = refresh_choice_reference(**kwargs)

    assert first.errors == second.errors == {}
    assert first.previous_snapshot_date == date(2026, 8, 30)
    assert first.current_count == 2
    assert first.added_symbols == ["300001.SZ"]
    assert first.removed_symbols == ["601988.SH"]
    assert first.modified_symbols == ["000001.SZ"]
    assert first.unchanged_count == 0
    assert first.calendar_received_rows == first.calendar_stored_rows == 14
    assert second.added_symbols == first.added_symbols
    assert second.removed_symbols == first.removed_symbols
    assert second.modified_symbols == first.modified_symbols

    snapshots = database.query_universe_snapshots()
    changes = database.query_master_changes(snapshot_date="2026-08-31")
    master = database.query_security_master(source="choice")
    assert len(snapshots) == 4
    assert len(changes) == 3
    assert set(changes["change_type"]) == {"added", "removed", "modified"}
    assert len(database.query_reference_refresh_runs()) == 2
    assert len(database.query_trading_calendar(
        market="CNSESH", start_date="2026-08-24", end_date="2026-08-30"
    )) == 7

    # 退出当前板块只记录 membership change，不擅自推断为退市。
    removed_status = master.loc[master["symbol"] == "601988.SH", "status"].item()
    assert removed_status == "active"
    assert fake.stop_calls == 2


def test_first_snapshot_is_a_baseline_not_mass_additions(monkeypatch, tmp_path):
    fake = FakeChoiceRefreshSDK()
    monkeypatch.setitem(sys.modules, "EmQuantAPI", SimpleNamespace(c=fake))
    monkeypatch.setenv("CHOICE_LOGIN_MODE", "userinfo")

    result = refresh_choice_reference(
        snapshot_date="2026-08-31",
        calendar_start_date="2026-08-24",
        calendar_end_date="2026-08-30",
        markets=["CNSESH"],
        database_path=tmp_path / "baseline.db",
    )

    assert result.previous_snapshot_date is None
    assert result.added_symbols == []
    assert result.removed_symbols == []
    assert result.modified_symbols == []
    assert result.unchanged_count == result.current_count == 2
