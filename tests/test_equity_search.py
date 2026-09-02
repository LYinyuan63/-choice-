from datetime import date

from qianji_data_mini.db import Database
from qianji_data_mini.models import SecurityMaster
from qianji_data_mini.openbb_provider.equity_search import (
    QianjiEquitySearchFetcher,
    QianjiEquitySearchQueryParams,
)
from qianji_data_mini.openbb_provider.provider import provider


def seed_master(path):
    database = Database(path)
    database.upsert_security_master(
        [
            SecurityMaster(
                symbol="000001.SZ",
                name="平安银行",
                exchange="SZSE",
                asset_type="equity",
                list_date=date(1991, 4, 3),
                as_of_date=date(2026, 8, 31),
            ),
            SecurityMaster(
                symbol="601988.SH",
                name="中国银行",
                exchange="SSE",
                asset_type="equity",
                list_date=date(2006, 7, 5),
                as_of_date=date(2026, 8, 31),
            ),
            SecurityMaster(
                symbol="510300.SH",
                name="华泰柏瑞沪深300ETF",
                exchange="SSE",
                asset_type="etf",
                as_of_date=date(2026, 8, 31),
            ),
        ]
    )
    return database


def test_database_searches_symbol_and_chinese_name(tmp_path):
    database = seed_master(tmp_path / "search.db")

    by_symbol = database.search_security_master(
        query="000001.SZ", is_symbol=True
    )
    by_name = database.search_security_master(query="银行")
    etf = database.search_security_master(query="沪深300", asset_type="etf")

    assert [item["symbol"] for item in by_symbol] == ["000001.SZ"]
    assert {item["symbol"] for item in by_name} == {"000001.SZ", "601988.SH"}
    assert [item["symbol"] for item in etf] == ["510300.SH"]


def test_qianji_equity_search_fetcher_reads_configured_database(
    monkeypatch, tmp_path
):
    database_path = tmp_path / "search.db"
    seed_master(database_path)
    monkeypatch.setenv("QIANJI_DB_PATH", str(database_path))

    query = QianjiEquitySearchFetcher.transform_query(
        {"query": "平安银行", "is_symbol": False, "source": "choice"}
    )
    raw = QianjiEquitySearchFetcher.extract_data(query, credentials=None)
    result = QianjiEquitySearchFetcher.transform_data(query, raw)

    assert len(result) == 1
    assert result[0].symbol == "000001.SZ"
    assert result[0].name == "平安银行"
    assert result[0].source == "choice"
    assert result[0].exchange == "SZSE"


def test_provider_registers_equity_search():
    assert provider.name == "qianji"
    assert set(provider.fetcher_dict) == {
        "EquityHistorical",
        "EquitySearch",
        "EquityQuote",
        "IncomeStatement",
        "BalanceSheet",
        "CashFlowStatement",
        "HistoricalDividends",
    }


def test_query_is_trimmed():
    query = QianjiEquitySearchQueryParams(query="  中国银行  ")
    assert query.query == "中国银行"
