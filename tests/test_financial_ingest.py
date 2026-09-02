import sys
from types import SimpleNamespace

from qianji_data_mini import Database, ingest_choice_financial_sample


class FakeChoiceFinancialSDK:
    def __init__(self):
        self.start_calls = 0
        self.stop_calls = 0
        self.css_calls = []

    def start(self, options):
        del options
        self.start_calls += 1
        return SimpleNamespace(ErrorCode=0, ErrorMsg="success")

    def stop(self):
        self.stop_calls += 1
        return SimpleNamespace(ErrorCode=0, ErrorMsg="success")

    def css(self, codes, indicators, options):
        self.css_calls.append((codes, indicators, options))
        names = indicators.split(",")
        if "BAD" in names:
            return SimpleNamespace(ErrorCode=1001, ErrorMsg="invalid indicator")
        values = {
            "REV": 100.0,
            "ASSET": "1,000.5",
            "OCF": 80,
            "DIVTXT": "10派5元",
        }
        return SimpleNamespace(
            ErrorCode=0,
            ErrorMsg="success",
            Codes=codes.split(","),
            Indicators=names,
            Data={
                code: [values[name] for name in names]
                for code in codes.split(",")
            },
        )


def test_choice_financial_sample_is_probed_and_ingested_idempotently(
    monkeypatch, tmp_path
):
    fake = FakeChoiceFinancialSDK()
    monkeypatch.setitem(sys.modules, "EmQuantAPI", SimpleNamespace(c=fake))
    monkeypatch.setenv("CHOICE_LOGIN_MODE", "userinfo")
    database_path = tmp_path / "financial.db"
    candidates = {
        "income": ["REV", "BAD"],
        "balance": ["ASSET"],
        "cashflow": ["OCF"],
        "dividend": ["DIVTXT"],
    }
    kwargs = {
        "symbols": ["000001.SZ", "600519.SH"],
        "report_dates": ["2025-12-31", "2026-06-30"],
        "indicator_candidates": candidates,
        "database_path": database_path,
    }

    first = ingest_choice_financial_sample(**kwargs)
    second = ingest_choice_financial_sample(**kwargs)
    database = Database(database_path)
    statements = database.query_financial_statement_facts(
        symbols=kwargs["symbols"]
    )
    dividends = database.query_dividend_facts(symbols=kwargs["symbols"])

    assert first.errors == second.errors == {}
    assert first.selected_indicators == {
        "income": ["REV"],
        "balance": ["ASSET"],
        "cashflow": ["OCF"],
        "dividend": ["DIVTXT"],
    }
    assert "BAD" in first.rejected_indicators["income"]
    assert first.statement_received_rows == first.statement_stored_rows == 12
    assert first.dividend_received_rows == first.dividend_stored_rows == 4
    assert len(statements) == 12
    assert len(dividends) == 4
    assert statements.loc[statements["indicator"] == "ASSET", "value_numeric"].eq(1000.5).all()
    assert dividends["value_text"].eq("10派5元").all()
    assert dividends["value_numeric"].isna().all()
    assert set(statements["unit"]) == set(dividends["unit"]) == {"vendor_raw"}
    assert len(database.query_financial_ingestion_runs()) == 2
    assert fake.stop_calls == 2
