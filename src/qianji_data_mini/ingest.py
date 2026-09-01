"""Ingestion orchestration shared by CLI, REST and notebooks."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from qianji_data_mini.adapters.registry import create_adapter
from qianji_data_mini.db import Database
from qianji_data_mini.models import IngestResult


def parse_date(value: date | str) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def ingest_daily(
    *,
    source: str,
    symbols: list[str] | str,
    start_date: date | str,
    end_date: date | str,
    database_path: str | Path | None = None,
) -> IngestResult:
    symbol_list = [item.strip().upper() for item in (symbols.split(",") if isinstance(symbols, str) else symbols) if item.strip()]
    start = parse_date(start_date)
    end = parse_date(end_date)
    if start > end:
        raise ValueError("start_date 不能晚于 end_date")

    started = datetime.now(timezone.utc)
    database = Database(database_path)
    adapter = create_adapter(source)
    bars = []
    failures: dict[str, str] = {}
    try:
        for symbol in symbol_list:
            try:
                bars.extend(adapter.fetch_daily(symbol, start, end))
            except Exception as exc:
                failures[symbol] = f"{type(exc).__name__}: {exc}"
    finally:
        adapter.close()
    stored = database.upsert_daily(bars)
    finished = datetime.now(timezone.utc)
    database.log_ingestion(
        source=source.lower(), symbols=symbol_list, start_date=start, end_date=end,
        received_rows=len(bars), stored_rows=stored, failed_symbols=failures,
        started_at=started.isoformat(), finished_at=finished.isoformat(),
    )
    return IngestResult(
        source=source.lower(), requested_symbols=symbol_list,
        received_rows=len(bars), stored_rows=stored, failed_symbols=failures,
        started_at=started, finished_at=finished,
    )

