import asyncio
from datetime import date

from qianji_data_mini.db import Database
from qianji_data_mini.models import DividendFact, FinancialStatementFact
from qianji_data_mini.openbb_provider.dividends import (
    QianjiHistoricalDividendsFetcher,
)
from qianji_data_mini.openbb_provider.financial_statements import (
    QianjiBalanceSheetFetcher,
    QianjiCashFlowStatementFetcher,
    QianjiIncomeStatementFetcher,
)


def seed_financial_database(path):
    database = Database(path)
    statement_fields = {
        "income": {
            "OPERATEREVE": 100.0,
            "NETPROFIT": 20.0,
            "PARENTNETPROFIT": 18.0,
        },
        "balance": {
            "SUMASSET": 1000.0,
            "SUMLIAB": 400.0,
            "SUMSHEQUITY": 600.0,
        },
        "cashflow": {
            "NETOPERATECASHFLOW": 80.0,
            "NETINVCASHFLOW": -30.0,
            "NETFINACASHFLOW": 10.0,
            "NICASHEQUI": 60.0,
        },
    }
    statements = []
    for report_date, multiplier in (
        (date(2025, 12, 31), 1.0),
        (date(2026, 6, 30), 2.0),
    ):
        for statement_type, fields in statement_fields.items():
            for indicator, value in fields.items():
                statements.append(
                    FinancialStatementFact(
                        symbol="000001.SZ",
                        statement_type=statement_type,
                        report_date=report_date,
                        indicator=indicator,
                        value_numeric=value * multiplier,
                        value_text=str(value * multiplier),
                        unit="CNY",
                    )
                )
    database.upsert_financial_statement_facts(statements)

    dividend_values = {
        "DIVWAY": (None, "10派5元", "text"),
        "DIVCASHPSBFTAX": (0.5, "0.5", "CNY/share"),
        "DIVCASHPSAFTAX": (None, "0.45或0.50", "CNY/share"),
        "DIVSTOCKPSRATIO": (None, None, "vendor_raw_ratio"),
        "DIVCAPITPSRATIO": (None, None, "vendor_raw_ratio"),
        "DIVRTISSBASESHARES": (10000.0, "10000", "10k_share"),
        "DIVIMPLANNCDATE": (None, "2026/6/1", "date"),
        "DIVRECORDDATE": (None, "06/15/2026", "date"),
        "DIVEXDATE": (None, "06/16/2026", "date"),
        "DIVPAYDATE": (None, "06/16/2026", "date"),
    }
    dividends = [
        DividendFact(
            symbol="000001.SZ",
            report_date=date(2025, 12, 31),
            indicator=indicator,
            value_numeric=value_numeric,
            value_text=value_text,
            unit=unit,
        )
        for indicator, (value_numeric, value_text, unit) in dividend_values.items()
    ]
    database.upsert_dividend_facts(dividends)
    return database


def test_statement_fetchers_pivot_sqlite_facts(monkeypatch, tmp_path):
    database_path = tmp_path / "financial_provider.db"
    seed_financial_database(database_path)
    monkeypatch.setenv("QIANJI_DB_PATH", str(database_path))

    income = asyncio.run(
        QianjiIncomeStatementFetcher.fetch_data(
            {"symbol": "000001.SZ", "limit": 1}, credentials={}
        )
    )
    balance = asyncio.run(
        QianjiBalanceSheetFetcher.fetch_data(
            {
                "symbol": "000001.SZ",
                "start_date": date(2025, 1, 1),
                "end_date": date(2025, 12, 31),
            },
            credentials={},
        )
    )
    cash = asyncio.run(
        QianjiCashFlowStatementFetcher.fetch_data(
            {"symbol": "000001.SZ", "limit": 5}, credentials={}
        )
    )

    assert len(income) == 1
    assert income[0].period_ending == date(2026, 6, 30)
    assert income[0].fiscal_period == "Q2"
    assert income[0].revenue == 200.0
    assert income[0].net_income_attributable_to_parent == 36.0
    assert income[0].reported_currency == "CNY"

    assert len(balance) == 1
    assert balance[0].period_ending == date(2025, 12, 31)
    assert balance[0].total_assets == 1000.0
    assert balance[0].total_liabilities == 400.0
    assert balance[0].total_common_equity == 600.0

    assert len(cash) == 2
    assert cash[0].net_cash_from_operating_activities == 160.0
    assert cash[0].net_cash_from_investing_activities == -60.0
    assert cash[0].net_cash_from_financing_activities == 20.0
    assert cash[0].net_change_in_cash_and_equivalents == 120.0


def test_dividend_fetcher_maps_cash_event_and_filters_ex_date(monkeypatch, tmp_path):
    database_path = tmp_path / "dividend_provider.db"
    seed_financial_database(database_path)
    monkeypatch.setenv("QIANJI_DB_PATH", str(database_path))

    results = asyncio.run(
        QianjiHistoricalDividendsFetcher.fetch_data(
            {
                "symbol": "000001.SZ",
                "start_date": date(2026, 1, 1),
                "end_date": date(2026, 12, 31),
            },
            credentials={},
        )
    )

    assert len(results) == 1
    assert results[0].ex_dividend_date == date(2026, 6, 16)
    assert results[0].amount == 0.5
    assert results[0].amount_after_tax is None
    assert results[0].amount_after_tax_text == "0.45或0.50"
    assert results[0].dividend_plan == "10派5元"
    assert results[0].record_date == date(2026, 6, 15)
    assert results[0].payment_date == date(2026, 6, 16)
    assert results[0].source == "choice"


def test_database_statement_type_filter(tmp_path):
    database = seed_financial_database(tmp_path / "filter.db")
    frame = database.query_financial_statement_facts(
        symbols=["000001.SZ"], statement_type="balance"
    )
    assert set(frame["statement_type"]) == {"balance"}
    assert len(frame) == 6
