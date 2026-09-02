import re
import sys
from types import SimpleNamespace

import pandas as pd

from qianji_data_mini import Database, ingest_choice_financial_sample


class FakeChoiceFinancialSDK:
    def __init__(self):
        self.start_calls = 0
        self.stop_calls = 0
        self.ctr_calls = []

    def start(self, options):
        del options
        self.start_calls += 1
        return SimpleNamespace(ErrorCode=0, ErrorMsg="success")

    def stop(self):
        self.stop_calls += 1
        return SimpleNamespace(ErrorCode=0, ErrorMsg="success")

    @staticmethod
    def _option(options, name):
        match = re.search(rf"(?:^|,){name}=([^,]+)", options, flags=re.I)
        return match.group(1) if match else None

    def ctr(self, report_name, indicators, options):
        self.ctr_calls.append((report_name, indicators, options))
        fields = indicators.upper().split(",")
        symbol = self._option(options, "SecuCode").upper()
        assert options.endswith("Ispandas=1")

        if report_name == "DividendImplementationInfo":
            rows = []
            for report_date, announcement_date in (
                ("12/31/2025", "4/10/2026"),
                ("6/30/2026", "8/30/2026"),
            ):
                values = {
                    "SECUCODE": symbol,
                    "REPORTDATE": report_date,
                    "DIVWAY": "10派5元",
                    "DIVCASHPSBFTAX": 0.5,
                    "DIVCASHPSAFTAX": "每10股派4.5元（税后）",
                    "DIVSTOCKPSRATIO": None,
                    "DIVCAPITPSRATIO": None,
                    "DIVRTISSBASESHARES": 10000,
                    "SHAREBASEDATE": report_date,
                    "DIVIMPLANNCDATE": announcement_date,
                    "DIVRECORDDATE": "7/15/2026",
                    "DIVEXDATE": "7/17/2026",
                    "DIVPAYDATE": "7/17/2026",
                }
                rows.append({field: values[field] for field in fields})
            return pd.DataFrame(rows)

        report_date = self._option(options, "ReportDate")
        values = {
            "REPORTDATE": pd.Timestamp(report_date),
            "OPERATEREVE": 100.0,
            "NETPROFIT": 20.0,
            "PARENTNETPROFIT": 18.0,
            "SUMASSET": "1,000.5",
            "SUMLIAB": 400.0,
            "SUMSHEQUITY": 600.5,
            "NETOPERATECASHFLOW": 80.0,
            "NETINVCASHFLOW": -30.0,
            "NETFINACASHFLOW": 10.0,
            "NICASHEQUI": 60.0,
        }
        return pd.DataFrame([{field: values[field] for field in fields}])


def test_choice_ctr_financial_sample_is_ingested_idempotently(monkeypatch, tmp_path):
    fake = FakeChoiceFinancialSDK()
    monkeypatch.setitem(sys.modules, "EmQuantAPI", SimpleNamespace(c=fake))
    monkeypatch.setenv("CHOICE_LOGIN_MODE", "userinfo")
    database_path = tmp_path / "financial.db"
    kwargs = {
        "symbols": ["000001.SZ", "600519.SH"],
        "report_dates": ["2025-12-31", "2026-06-30"],
        "database_path": database_path,
    }

    first = ingest_choice_financial_sample(**kwargs)
    second = ingest_choice_financial_sample(**kwargs)
    database = Database(database_path)
    statements = database.query_financial_statement_facts(symbols=kwargs["symbols"])
    dividends = database.query_dividend_facts(symbols=kwargs["symbols"])

    assert first.errors == second.errors == {}
    assert first.rejected_indicators == second.rejected_indicators == {
        "income": {}, "balance": {}, "cashflow": {}, "dividend": {}
    }
    assert first.statement_received_rows == first.statement_stored_rows == 40
    assert first.dividend_received_rows == first.dividend_stored_rows == 44
    assert len(statements) == 40
    assert len(dividends) == 44
    assert statements.loc[
        statements["indicator"] == "SUMASSET", "value_numeric"
    ].eq(1000.5).all()
    assert set(statements["unit"]) == {"CNY"}
    assert dividends.loc[
        dividends["indicator"] == "DIVCASHPSBFTAX", "unit"
    ].eq("CNY/share").all()
    assert dividends.loc[
        dividends["indicator"] == "DIVRTISSBASESHARES", "unit"
    ].eq("10k_share").all()
    tax_after = dividends[dividends["indicator"] == "DIVCASHPSAFTAX"]
    assert tax_after["value_numeric"].isna().all()
    assert tax_after["value_text"].str.contains("税后").all()
    ex_dates = dividends[dividends["indicator"] == "DIVEXDATE"]
    assert ex_dates["value_text"].eq("2026-07-17").all()
    assert len(database.query_financial_ingestion_runs()) == 2
    assert fake.start_calls == fake.stop_calls == 2
    assert len(fake.ctr_calls) == 28
    assert all(call[0] != "" for call in fake.ctr_calls)


def test_choice_ctr_error_is_recorded_without_discarding_other_requests(
    monkeypatch, tmp_path
):
    fake = FakeChoiceFinancialSDK()
    original_ctr = fake.ctr

    def partially_failing_ctr(report_name, indicators, options):
        if report_name == "BalanceStatementSHSZ" and "600519.SH" in options:
            return SimpleNamespace(ErrorCode=1001, ErrorMsg="no permission")
        return original_ctr(report_name, indicators, options)

    fake.ctr = partially_failing_ctr
    monkeypatch.setitem(sys.modules, "EmQuantAPI", SimpleNamespace(c=fake))
    monkeypatch.setenv("CHOICE_LOGIN_MODE", "userinfo")

    result = ingest_choice_financial_sample(
        symbols=["000001.SZ", "600519.SH"],
        report_dates=["2025-12-31"],
        database_path=tmp_path / "partial.db",
    )

    assert "balance:600519.SH:2025-12-31" in result.errors
    assert result.statement_received_rows == 17
    assert result.dividend_received_rows == 22
    assert fake.stop_calls == 1


def test_choice_data_limit_stops_remaining_financial_requests(monkeypatch, tmp_path):
    fake = FakeChoiceFinancialSDK()
    original_ctr = fake.ctr

    def quota_limited_ctr(report_name, indicators, options):
        if report_name != "DividendImplementationInfo":
            fake.ctr_calls.append((report_name, indicators, options))
            return SimpleNamespace(
                ErrorCode=10001029,
                ErrorMsg="data limit exceeded",
            )
        return original_ctr(report_name, indicators, options)

    fake.ctr = quota_limited_ctr
    monkeypatch.setitem(sys.modules, "EmQuantAPI", SimpleNamespace(c=fake))
    monkeypatch.setenv("CHOICE_LOGIN_MODE", "userinfo")

    result = ingest_choice_financial_sample(
        symbols=["000001.SZ", "600519.SH"],
        report_dates=["2025-12-31"],
        database_path=tmp_path / "quota.db",
    )

    assert result.statement_received_rows == 0
    assert result.dividend_received_rows == 22
    assert "income:000001.SZ:2025-12-31" in result.errors
    assert "financial_quota_circuit_breaker" in result.errors
    assert "跳过5个财务请求" in result.errors["financial_quota_circuit_breaker"]
    assert len(fake.ctr_calls) == 3  # one failed statement plus two dividends
    assert fake.stop_calls == 1
