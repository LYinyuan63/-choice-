import asyncio
from datetime import datetime, timezone

from qianji_data_mini.db import Database
from qianji_data_mini.models import QuoteSnapshot
from qianji_data_mini.openbb_provider.equity_quote import QianjiEquityQuoteFetcher


def _quote(symbol: str, quote_time: str, price: float) -> QuoteSnapshot:
    return QuoteSnapshot(
        symbol=symbol,
        quote_time=datetime.fromisoformat(quote_time),
        open=price - 0.2,
        high=price + 0.3,
        low=price - 0.4,
        last_price=price,
        previous_close=price - 0.1,
        volume=12300,
        amount=789000,
        fetched_at=datetime.now(timezone.utc),
    )


def test_quote_snapshot_upsert_and_latest_query(tmp_path):
    database = Database(tmp_path / "quotes.db")
    first = _quote("000001.SZ", "2026-09-02T14:20:00+08:00", 10.4)
    latest = _quote("000001.SZ", "2026-09-02T14:21:00+08:00", 10.5)

    assert database.upsert_quote_snapshots([first, latest]) == 2
    assert database.upsert_quote_snapshots([latest]) == 1
    all_rows = database.query_quote_snapshots(symbols=["000001.SZ"])
    latest_rows = database.query_quote_snapshots(
        symbols=["000001.SZ"], latest_only=True
    )

    assert len(all_rows) == 2
    assert len(latest_rows) == 1
    assert latest_rows.iloc[0]["last_price"] == 10.5


def test_qianji_quote_fetcher_reads_sqlite(monkeypatch, tmp_path):
    database_path = tmp_path / "provider_quotes.db"
    database = Database(database_path)
    database.upsert_quote_snapshots(
        [
            _quote("000001.SZ", "2026-09-02T14:21:00+08:00", 10.5),
            _quote("600519.SH", "2026-09-02T14:21:01+08:00", 1510.0),
        ]
    )
    monkeypatch.setenv("QIANJI_DB_PATH", str(database_path))

    results = asyncio.run(
        QianjiEquityQuoteFetcher.fetch_data(
            {"symbol": "000001.SZ,600519.SH", "source": "choice"},
            credentials={},
        )
    )

    assert len(results) == 2
    assert results[0].symbol == "000001.SZ"
    assert results[0].last_price == 10.5
    assert results[0].prev_close == 10.4
    assert results[0].change_percent > 0
    assert results[0].source == "choice"
