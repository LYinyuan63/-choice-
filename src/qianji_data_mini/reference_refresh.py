"""Snapshot-aware Choice master-data and long-calendar refresh."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from qianji_data_mini.adapters.choice import ChoiceAdapter
from qianji_data_mini.db import Database
from qianji_data_mini.models import ReferenceRefreshResult, SecurityMaster


def _parse_date(value: date | str) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def _master_values(item: SecurityMaster) -> dict[str, object]:
    return {
        "name": item.name,
        "exchange": item.exchange,
        "asset_type": item.asset_type,
        "currency": item.currency,
        "list_date": item.list_date.isoformat() if item.list_date else None,
        "delist_date": item.delist_date.isoformat() if item.delist_date else None,
        "status": item.status,
    }


def refresh_choice_reference(
    *,
    snapshot_date: date | str,
    calendar_start_date: date | str,
    calendar_end_date: date | str,
    markets: list[str] | tuple[str, ...] = ("CNSESH", "CNSESZ"),
    sector_code: str = "001004",
    universe: str = "all_a_001004",
    batch_size: int = 100,
    bootstrap_from_master: bool = True,
    database_path: str | Path | None = None,
) -> ReferenceRefreshResult:
    """Refresh Choice identities, membership snapshots, changes and calendar."""
    snapshot = _parse_date(snapshot_date)
    start = _parse_date(calendar_start_date)
    end = _parse_date(calendar_end_date)
    if start > end:
        raise ValueError("calendar_start_date 不能晚于 calendar_end_date。")
    requested_markets = list(
        dict.fromkeys(str(item).strip().upper() for item in markets if str(item).strip())
    )
    if not requested_markets:
        raise ValueError("至少需要一个交易市场。")

    source = "choice"
    started = datetime.now(timezone.utc)
    database = Database(database_path)
    previous_date = database.latest_universe_snapshot_date(
        source=source, universe=universe, before=snapshot
    )
    if previous_date is None and bootstrap_from_master:
        previous_date = database.bootstrap_snapshot_from_master(
            source=source,
            universe=universe,
            before=snapshot,
            captured_at=started.isoformat(),
        )
    previous_symbols = set(
        database.universe_symbols(
            source=source, universe=universe, snapshot_date=previous_date
        )
        if previous_date
        else []
    )
    previous_master = (
        database.universe_master_values(
            source=source,
            universe=universe,
            snapshot_date=previous_date,
        )
        if previous_date
        else {}
    )

    errors: dict[str, str] = {}
    current_symbols: list[str] = []
    master_records: list[SecurityMaster] = []
    calendar_records = []
    adapter = ChoiceAdapter()
    try:
        try:
            current_symbols = adapter.fetch_sector_symbols(
                sector_code=sector_code, as_of_date=snapshot
            )
        except Exception as exc:
            errors["sector"] = f"{type(exc).__name__}: {exc}"

        if current_symbols:
            try:
                master_records = adapter.fetch_security_master(
                    symbols=current_symbols,
                    as_of_date=snapshot,
                    batch_size=batch_size,
                )
            except Exception as exc:
                errors["security_master"] = f"{type(exc).__name__}: {exc}"

        for market in requested_markets:
            try:
                calendar_records.extend(
                    adapter.fetch_trading_calendar(
                        market=market, start_date=start, end_date=end
                    )
                )
            except Exception as exc:
                errors[f"trading_calendar:{market}"] = f"{type(exc).__name__}: {exc}"
    finally:
        adapter.close()

    current_set = set(current_symbols)
    added = sorted(current_set - previous_symbols) if previous_date else []
    removed = sorted(previous_symbols - current_set) if previous_date else []
    current_master = {item.symbol: item for item in master_records}
    modified: list[str] = []
    changed_fields: dict[str, list[str]] = {}
    if previous_date and len(current_master) == len(current_set):
        for symbol in sorted(previous_symbols & current_set):
            old = previous_master.get(symbol)
            new = current_master.get(symbol)
            if old is None or new is None:
                continue
            new_values = _master_values(new)
            fields = [
                field for field, value in new_values.items()
                if old.get(field) != value
            ]
            if fields:
                modified.append(symbol)
                changed_fields[symbol] = fields

    security_stored = database.upsert_security_master(master_records)
    calendar_stored = database.upsert_trading_calendar(calendar_records)
    detected = datetime.now(timezone.utc)

    if current_symbols:
        database.replace_universe_snapshot(
            source=source,
            universe=universe,
            snapshot_date=snapshot,
            symbols=current_symbols,
            captured_at=detected.isoformat(),
            master_by_symbol={
                symbol: _master_values(item)
                for symbol, item in current_master.items()
            },
        )
        changes = [
            {"symbol": symbol, "change_type": "added", "changed_fields": ["membership"]}
            for symbol in added
        ] + [
            {"symbol": symbol, "change_type": "removed", "changed_fields": ["membership"]}
            for symbol in removed
        ] + [
            {"symbol": symbol, "change_type": "modified", "changed_fields": changed_fields[symbol]}
            for symbol in modified
        ]
        database.replace_master_changes(
            source=source,
            universe=universe,
            snapshot_date=snapshot,
            previous_snapshot_date=previous_date,
            changes=changes,
            detected_at=detected.isoformat(),
        )

    unchanged = (
        len((previous_symbols & current_set) - set(modified))
        if previous_date
        else len(current_set)
    )
    finished = datetime.now(timezone.utc)
    database.log_reference_refresh(
        source=source,
        universe=universe,
        snapshot_date=snapshot,
        previous_snapshot_date=previous_date,
        current_count=len(current_set),
        added_count=len(added),
        removed_count=len(removed),
        modified_count=len(modified),
        unchanged_count=unchanged,
        calendar_start_date=start,
        calendar_end_date=end,
        calendar_received_rows=len(calendar_records),
        calendar_stored_rows=calendar_stored,
        errors=errors,
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
    )
    return ReferenceRefreshResult(
        universe=universe,
        snapshot_date=snapshot,
        previous_snapshot_date=_parse_date(previous_date) if previous_date else None,
        current_symbols=sorted(current_set),
        current_count=len(current_set),
        added_symbols=added,
        removed_symbols=removed,
        modified_symbols=modified,
        unchanged_count=unchanged,
        security_received_rows=len(master_records),
        security_stored_rows=security_stored,
        calendar_received_rows=len(calendar_records),
        calendar_stored_rows=calendar_stored,
        errors=errors,
        started_at=started,
        finished_at=finished,
    )
