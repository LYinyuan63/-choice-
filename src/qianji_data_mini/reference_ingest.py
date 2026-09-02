"""Choice reference-data ingestion for security master and trading calendar."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from qianji_data_mini.adapters.choice import ChoiceAdapter
from qianji_data_mini.db import Database
from qianji_data_mini.models import ReferenceIngestResult


def _parse_date(value: date | str) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def ingest_choice_reference(
    *,
    symbols: list[str] | str,
    calendar_start_date: date | str,
    calendar_end_date: date | str,
    markets: list[str] | tuple[str, ...] = ("CNSESH", "CNSESZ"),
    as_of_date: date | str | None = None,
    sector_code: str | None = None,
    batch_size: int = 100,
    database_path: str | Path | None = None,
) -> ReferenceIngestResult:
    """Fetch and idempotently store Choice identity and calendar records."""
    start = _parse_date(calendar_start_date)
    end = _parse_date(calendar_end_date)
    snapshot = _parse_date(as_of_date or end)
    if start > end:
        raise ValueError("calendar_start_date 不能晚于 calendar_end_date。")

    requested_symbols = list(
        dict.fromkeys(
            item.strip().upper()
            for item in (symbols.split(",") if isinstance(symbols, str) else symbols)
            if item.strip()
        )
    )
    requested_markets = list(
        dict.fromkeys(str(item).strip().upper() for item in markets if str(item).strip())
    )
    if not requested_symbols and not sector_code:
        raise ValueError("必须提供证券代码或sector_code。")
    if not requested_markets:
        raise ValueError("至少需要一个交易市场。")

    started = datetime.now(timezone.utc)
    database = Database(database_path)
    adapter = ChoiceAdapter()
    errors: dict[str, str] = {}
    master_records = []
    calendar_records = []

    try:
        if sector_code:
            try:
                requested_symbols = adapter.fetch_sector_symbols(
                    sector_code=sector_code,
                    as_of_date=snapshot,
                )
            except Exception as exc:
                errors["sector"] = f"{type(exc).__name__}: {exc}"
                requested_symbols = []

        if requested_symbols:
            try:
                master_records = adapter.fetch_security_master(
                    symbols=requested_symbols,
                    as_of_date=snapshot,
                    batch_size=batch_size,
                )
            except Exception as exc:
                errors["security_master"] = f"{type(exc).__name__}: {exc}"

        for market in requested_markets:
            try:
                calendar_records.extend(
                    adapter.fetch_trading_calendar(
                        market=market,
                        start_date=start,
                        end_date=end,
                    )
                )
            except Exception as exc:
                errors[f"trading_calendar:{market}"] = f"{type(exc).__name__}: {exc}"
    finally:
        adapter.close()

    security_stored = database.upsert_security_master(master_records)
    calendar_stored = database.upsert_trading_calendar(calendar_records)
    finished = datetime.now(timezone.utc)

    security_errors = {
        key: value for key, value in errors.items()
        if key in {"sector", "security_master"}
    }
    calendar_errors = {
        key: value for key, value in errors.items()
        if key.startswith("trading_calendar:")
    }
    database.log_reference_ingestion(
        source="choice",
        dataset="security_master",
        request_payload={
            "symbols": requested_symbols,
            "sector_code": sector_code,
            "as_of_date": snapshot.isoformat(),
        },
        received_rows=len(master_records),
        stored_rows=security_stored,
        errors=security_errors,
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
    )
    database.log_reference_ingestion(
        source="choice",
        dataset="trading_calendar",
        request_payload={
            "markets": requested_markets,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        },
        received_rows=len(calendar_records),
        stored_rows=calendar_stored,
        errors=calendar_errors,
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
    )

    return ReferenceIngestResult(
        requested_symbols=requested_symbols,
        requested_markets=requested_markets,
        security_received_rows=len(master_records),
        security_stored_rows=security_stored,
        calendar_received_rows=len(calendar_records),
        calendar_stored_rows=calendar_stored,
        errors=errors,
        started_at=started,
        finished_at=finished,
    )
