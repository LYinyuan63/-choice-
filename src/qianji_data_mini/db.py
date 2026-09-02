"""SQLite storage for the lightweight MVP."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Iterable

import pandas as pd

from qianji_data_mini.config import db_path as configured_db_path
from qianji_data_mini.config import source_priority
from qianji_data_mini.models import (
    DailyBar,
    DividendFact,
    FinancialStatementFact,
    SecurityMaster,
    TradingCalendarDay,
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_bar (
    source TEXT NOT NULL,
    symbol TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    adjustment TEXT NOT NULL DEFAULT 'unadjusted',
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    amount REAL,
    previous_close REAL,
    change_percent REAL,
    currency TEXT NOT NULL,
    timezone TEXT NOT NULL,
    volume_unit TEXT NOT NULL,
    amount_unit TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    raw_json TEXT,
    PRIMARY KEY (source, symbol, trade_date, adjustment)
);
CREATE INDEX IF NOT EXISTS idx_daily_bar_symbol_date
ON daily_bar(symbol, trade_date);

CREATE TABLE IF NOT EXISTS ingestion_run (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    requested_symbols TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    received_rows INTEGER NOT NULL,
    stored_rows INTEGER NOT NULL,
    failed_symbols TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS security_master (
    source TEXT NOT NULL,
    symbol TEXT NOT NULL,
    name TEXT NOT NULL,
    exchange TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    currency TEXT NOT NULL,
    list_date TEXT,
    delist_date TEXT,
    status TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    raw_json TEXT,
    PRIMARY KEY (source, symbol)
);
CREATE INDEX IF NOT EXISTS idx_security_master_exchange_status
ON security_master(exchange, status);

CREATE TABLE IF NOT EXISTS trading_calendar (
    source TEXT NOT NULL,
    market TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    is_open INTEGER NOT NULL CHECK (is_open IN (0, 1)),
    previous_open_date TEXT,
    next_open_date TEXT,
    timezone TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (source, market, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_trading_calendar_market_open
ON trading_calendar(market, is_open, trade_date);

CREATE TABLE IF NOT EXISTS reference_ingestion_run (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    dataset TEXT NOT NULL,
    request_payload TEXT NOT NULL,
    received_rows INTEGER NOT NULL,
    stored_rows INTEGER NOT NULL,
    errors TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS security_universe_snapshot (
    source TEXT NOT NULL,
    universe TEXT NOT NULL,
    snapshot_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    master_json TEXT NOT NULL DEFAULT '{}',
    captured_at TEXT NOT NULL,
    PRIMARY KEY (source, universe, snapshot_date, symbol)
);
CREATE INDEX IF NOT EXISTS idx_security_universe_snapshot_latest
ON security_universe_snapshot(source, universe, snapshot_date);

CREATE TABLE IF NOT EXISTS security_master_change (
    source TEXT NOT NULL,
    universe TEXT NOT NULL,
    snapshot_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    change_type TEXT NOT NULL CHECK (change_type IN ('added', 'removed', 'modified')),
    previous_snapshot_date TEXT,
    changed_fields TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    PRIMARY KEY (source, universe, snapshot_date, symbol, change_type)
);
CREATE INDEX IF NOT EXISTS idx_security_master_change_date
ON security_master_change(source, universe, snapshot_date, change_type);

CREATE TABLE IF NOT EXISTS reference_refresh_run (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    universe TEXT NOT NULL,
    snapshot_date TEXT NOT NULL,
    previous_snapshot_date TEXT,
    current_count INTEGER NOT NULL,
    added_count INTEGER NOT NULL,
    removed_count INTEGER NOT NULL,
    modified_count INTEGER NOT NULL,
    unchanged_count INTEGER NOT NULL,
    calendar_start_date TEXT NOT NULL,
    calendar_end_date TEXT NOT NULL,
    calendar_received_rows INTEGER NOT NULL,
    calendar_stored_rows INTEGER NOT NULL,
    errors TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS financial_statement_fact (
    source TEXT NOT NULL,
    symbol TEXT NOT NULL,
    statement_type TEXT NOT NULL
        CHECK (statement_type IN ('income', 'balance', 'cashflow')),
    report_date TEXT NOT NULL,
    indicator TEXT NOT NULL,
    value_numeric REAL,
    value_text TEXT,
    currency TEXT NOT NULL,
    unit TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    raw_json TEXT,
    PRIMARY KEY (source, symbol, statement_type, report_date, indicator)
);
CREATE INDEX IF NOT EXISTS idx_financial_statement_symbol_date
ON financial_statement_fact(symbol, report_date, statement_type);

CREATE TABLE IF NOT EXISTS dividend_fact (
    source TEXT NOT NULL,
    symbol TEXT NOT NULL,
    report_date TEXT NOT NULL,
    indicator TEXT NOT NULL,
    value_numeric REAL,
    value_text TEXT,
    currency TEXT NOT NULL,
    unit TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    raw_json TEXT,
    PRIMARY KEY (source, symbol, report_date, indicator)
);
CREATE INDEX IF NOT EXISTS idx_dividend_fact_symbol_date
ON dividend_fact(symbol, report_date);

CREATE TABLE IF NOT EXISTS financial_ingestion_run (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    requested_symbols TEXT NOT NULL,
    requested_report_dates TEXT NOT NULL,
    selected_indicators TEXT NOT NULL,
    rejected_indicators TEXT NOT NULL,
    statement_received_rows INTEGER NOT NULL,
    statement_stored_rows INTEGER NOT NULL,
    dividend_received_rows INTEGER NOT NULL,
    dividend_stored_rows INTEGER NOT NULL,
    errors TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else configured_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            snapshot_columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(security_universe_snapshot)"
                ).fetchall()
            }
            if "master_json" not in snapshot_columns:
                connection.execute(
                    "ALTER TABLE security_universe_snapshot "
                    "ADD COLUMN master_json TEXT NOT NULL DEFAULT '{}'"
                )

    def upsert_daily(self, bars: Iterable[DailyBar]) -> int:
        records = list(bars)
        if not records:
            return 0
        sql = """
        INSERT INTO daily_bar (
            source, symbol, trade_date, adjustment,
            open, high, low, close, volume, amount,
            previous_close, change_percent, currency, timezone,
            volume_unit, amount_unit, ingested_at, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, symbol, trade_date, adjustment) DO UPDATE SET
            open=excluded.open,
            high=excluded.high,
            low=excluded.low,
            close=excluded.close,
            volume=excluded.volume,
            amount=excluded.amount,
            previous_close=excluded.previous_close,
            change_percent=excluded.change_percent,
            currency=excluded.currency,
            timezone=excluded.timezone,
            volume_unit=excluded.volume_unit,
            amount_unit=excluded.amount_unit,
            ingested_at=excluded.ingested_at,
            raw_json=excluded.raw_json
        """
        values = [
            (
                item.source,
                item.symbol,
                item.date.isoformat(),
                item.adjustment,
                item.open,
                item.high,
                item.low,
                item.close,
                item.volume,
                item.amount,
                item.previous_close,
                item.change_percent,
                item.currency,
                item.timezone,
                item.volume_unit,
                item.amount_unit,
                item.ingested_at.isoformat(),
                json.dumps(item.raw, ensure_ascii=False, default=str),
            )
            for item in records
        ]
        with self.connect() as connection:
            connection.executemany(sql, values)
        return len(values)

    def upsert_security_master(self, records: Iterable[SecurityMaster]) -> int:
        items = list(records)
        if not items:
            return 0
        sql = """
        INSERT INTO security_master (
            source, symbol, name, exchange, asset_type, currency,
            list_date, delist_date, status, as_of_date, fetched_at, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, symbol) DO UPDATE SET
            name=excluded.name,
            exchange=excluded.exchange,
            asset_type=excluded.asset_type,
            currency=excluded.currency,
            list_date=excluded.list_date,
            delist_date=excluded.delist_date,
            status=excluded.status,
            as_of_date=excluded.as_of_date,
            fetched_at=excluded.fetched_at,
            raw_json=excluded.raw_json
        """
        values = [
            (
                item.source,
                item.symbol,
                item.name,
                item.exchange,
                item.asset_type,
                item.currency,
                item.list_date.isoformat() if item.list_date else None,
                item.delist_date.isoformat() if item.delist_date else None,
                item.status,
                item.as_of_date.isoformat(),
                item.fetched_at.isoformat(),
                json.dumps(item.raw, ensure_ascii=False, default=str),
            )
            for item in items
        ]
        with self.connect() as connection:
            connection.executemany(sql, values)
        return len(values)

    def upsert_trading_calendar(
        self,
        records: Iterable[TradingCalendarDay],
    ) -> int:
        items = list(records)
        if not items:
            return 0
        sql = """
        INSERT INTO trading_calendar (
            source, market, trade_date, is_open,
            previous_open_date, next_open_date, timezone, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, market, trade_date) DO UPDATE SET
            is_open=excluded.is_open,
            previous_open_date=excluded.previous_open_date,
            next_open_date=excluded.next_open_date,
            timezone=excluded.timezone,
            fetched_at=excluded.fetched_at
        """
        values = [
            (
                item.source,
                item.market,
                item.date.isoformat(),
                int(item.is_open),
                item.previous_open_date.isoformat() if item.previous_open_date else None,
                item.next_open_date.isoformat() if item.next_open_date else None,
                item.timezone,
                item.fetched_at.isoformat(),
            )
            for item in items
        ]
        with self.connect() as connection:
            connection.executemany(sql, values)
        return len(values)

    def log_reference_ingestion(
        self,
        *,
        source: str,
        dataset: str,
        request_payload: dict,
        received_rows: int,
        stored_rows: int,
        errors: dict[str, str],
        started_at: str,
        finished_at: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO reference_ingestion_run (
                    source, dataset, request_payload, received_rows,
                    stored_rows, errors, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source,
                    dataset,
                    json.dumps(request_payload, ensure_ascii=False, default=str),
                    received_rows,
                    stored_rows,
                    json.dumps(errors, ensure_ascii=False),
                    started_at,
                    finished_at,
                ),
            )

    def latest_universe_snapshot_date(
        self,
        *,
        source: str,
        universe: str,
        before: date | str | None = None,
    ) -> str | None:
        sql = """
            SELECT MAX(snapshot_date) FROM security_universe_snapshot
            WHERE source=? AND universe=?
        """
        params: list[str] = [source.lower(), universe]
        if before is not None:
            sql += " AND snapshot_date < ?"
            params.append(str(before))
        with self.connect() as connection:
            value = connection.execute(sql, params).fetchone()[0]
        return str(value) if value is not None else None

    def replace_universe_snapshot(
        self,
        *,
        source: str,
        universe: str,
        snapshot_date: date | str,
        symbols: Iterable[str],
        captured_at: str,
        master_by_symbol: dict[str, dict] | None = None,
    ) -> int:
        normalized = sorted(
            set(str(item).strip().upper() for item in symbols if str(item).strip())
        )
        snapshot = str(snapshot_date)
        with self.connect() as connection:
            connection.execute(
                """
                DELETE FROM security_universe_snapshot
                WHERE source=? AND universe=? AND snapshot_date=?
                """,
                (source.lower(), universe, snapshot),
            )
            connection.executemany(
                """
                INSERT INTO security_universe_snapshot (
                    source, universe, snapshot_date, symbol, master_json, captured_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        source.lower(), universe, snapshot, symbol,
                        json.dumps(
                            (master_by_symbol or {}).get(symbol, {}),
                            ensure_ascii=False,
                            default=str,
                        ),
                        captured_at,
                    )
                    for symbol in normalized
                ],
            )
        return len(normalized)

    def universe_symbols(
        self,
        *,
        source: str,
        universe: str,
        snapshot_date: date | str,
    ) -> list[str]:
        with self.connect() as connection:
            return [
                str(row[0])
                for row in connection.execute(
                    """
                    SELECT symbol FROM security_universe_snapshot
                    WHERE source=? AND universe=? AND snapshot_date=?
                    ORDER BY symbol
                    """,
                    (source.lower(), universe, str(snapshot_date)),
                ).fetchall()
            ]

    def universe_master_values(
        self,
        *,
        source: str,
        universe: str,
        snapshot_date: date | str,
    ) -> dict[str, dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT symbol, master_json FROM security_universe_snapshot
                WHERE source=? AND universe=? AND snapshot_date=?
                """,
                (source.lower(), universe, str(snapshot_date)),
            ).fetchall()
        values: dict[str, dict] = {}
        for row in rows:
            try:
                parsed = json.loads(row[1] or "{}")
            except json.JSONDecodeError:
                parsed = {}
            values[str(row[0])] = parsed if isinstance(parsed, dict) else {}
        return values

    def bootstrap_snapshot_from_master(
        self,
        *,
        source: str,
        universe: str,
        before: date | str,
        captured_at: str,
    ) -> str | None:
        with self.connect() as connection:
            snapshot = connection.execute(
                """
                SELECT MAX(as_of_date) FROM security_master
                WHERE source=? AND asset_type='equity' AND status='active'
                  AND as_of_date < ?
                """,
                (source.lower(), str(before)),
            ).fetchone()[0]
            if snapshot is None:
                return None
            rows = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT symbol, name, exchange, asset_type, currency,
                           list_date, delist_date, status
                    FROM security_master
                    WHERE source=? AND asset_type='equity' AND status='active'
                      AND as_of_date=?
                    ORDER BY symbol
                    """,
                    (source.lower(), snapshot),
                ).fetchall()
            ]
        self.replace_universe_snapshot(
            source=source,
            universe=universe,
            snapshot_date=str(snapshot),
            symbols=[row["symbol"] for row in rows],
            captured_at=captured_at,
            master_by_symbol={
                row["symbol"]: {
                    key: row[key]
                    for key in (
                        "name", "exchange", "asset_type", "currency",
                        "list_date", "delist_date", "status",
                    )
                }
                for row in rows
            },
        )
        return str(snapshot)

    def replace_master_changes(
        self,
        *,
        source: str,
        universe: str,
        snapshot_date: date | str,
        previous_snapshot_date: date | str | None,
        changes: Iterable[dict],
        detected_at: str,
    ) -> int:
        items = list(changes)
        snapshot = str(snapshot_date)
        with self.connect() as connection:
            connection.execute(
                """
                DELETE FROM security_master_change
                WHERE source=? AND universe=? AND snapshot_date=?
                """,
                (source.lower(), universe, snapshot),
            )
            connection.executemany(
                """
                INSERT INTO security_master_change (
                    source, universe, snapshot_date, symbol, change_type,
                    previous_snapshot_date, changed_fields, detected_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        source.lower(),
                        universe,
                        snapshot,
                        str(item["symbol"]).upper(),
                        str(item["change_type"]),
                        str(previous_snapshot_date) if previous_snapshot_date else None,
                        json.dumps(item.get("changed_fields", []), ensure_ascii=False),
                        detected_at,
                    )
                    for item in items
                ],
            )
        return len(items)

    def log_reference_refresh(
        self,
        *,
        source: str,
        universe: str,
        snapshot_date: date | str,
        previous_snapshot_date: date | str | None,
        current_count: int,
        added_count: int,
        removed_count: int,
        modified_count: int,
        unchanged_count: int,
        calendar_start_date: date | str,
        calendar_end_date: date | str,
        calendar_received_rows: int,
        calendar_stored_rows: int,
        errors: dict[str, str],
        started_at: str,
        finished_at: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO reference_refresh_run (
                    source, universe, snapshot_date, previous_snapshot_date,
                    current_count, added_count, removed_count, modified_count,
                    unchanged_count, calendar_start_date, calendar_end_date,
                    calendar_received_rows, calendar_stored_rows, errors,
                    started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source.lower(), universe, str(snapshot_date),
                    str(previous_snapshot_date) if previous_snapshot_date else None,
                    current_count, added_count, removed_count, modified_count,
                    unchanged_count, str(calendar_start_date), str(calendar_end_date),
                    calendar_received_rows, calendar_stored_rows,
                    json.dumps(errors, ensure_ascii=False), started_at, finished_at,
                ),
            )

    def query_universe_snapshots(
        self,
        *,
        source: str = "choice",
        universe: str = "all_a_001004",
        snapshot_date: date | str | None = None,
    ) -> pd.DataFrame:
        sql = """
            SELECT * FROM security_universe_snapshot
            WHERE source=? AND universe=?
        """
        params: list[str] = [source.lower(), universe]
        if snapshot_date is not None:
            sql += " AND snapshot_date=?"
            params.append(str(snapshot_date))
        sql += " ORDER BY snapshot_date, symbol"
        with self.connect() as connection:
            return pd.read_sql_query(sql, connection, params=params)

    def query_master_changes(
        self,
        *,
        source: str = "choice",
        universe: str = "all_a_001004",
        snapshot_date: date | str | None = None,
    ) -> pd.DataFrame:
        sql = """
            SELECT * FROM security_master_change
            WHERE source=? AND universe=?
        """
        params: list[str] = [source.lower(), universe]
        if snapshot_date is not None:
            sql += " AND snapshot_date=?"
            params.append(str(snapshot_date))
        sql += " ORDER BY snapshot_date, change_type, symbol"
        with self.connect() as connection:
            return pd.read_sql_query(sql, connection, params=params)

    def query_reference_refresh_runs(self) -> pd.DataFrame:
        with self.connect() as connection:
            return pd.read_sql_query(
                "SELECT * FROM reference_refresh_run ORDER BY run_id", connection
            )

    def upsert_financial_statement_facts(
        self, records: Iterable[FinancialStatementFact]
    ) -> int:
        items = list(records)
        if not items:
            return 0
        sql = """
        INSERT INTO financial_statement_fact (
            source, symbol, statement_type, report_date, indicator,
            value_numeric, value_text, currency, unit, fetched_at, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, symbol, statement_type, report_date, indicator)
        DO UPDATE SET
            value_numeric=excluded.value_numeric,
            value_text=excluded.value_text,
            currency=excluded.currency,
            unit=excluded.unit,
            fetched_at=excluded.fetched_at,
            raw_json=excluded.raw_json
        """
        values = [
            (
                item.source.lower(), item.symbol.upper(), item.statement_type,
                item.report_date.isoformat(), item.indicator.upper(),
                item.value_numeric, item.value_text, item.currency, item.unit,
                item.fetched_at.isoformat(),
                json.dumps(item.raw, ensure_ascii=False, default=str),
            )
            for item in items
        ]
        with self.connect() as connection:
            connection.executemany(sql, values)
        return len(values)

    def upsert_dividend_facts(self, records: Iterable[DividendFact]) -> int:
        items = list(records)
        if not items:
            return 0
        sql = """
        INSERT INTO dividend_fact (
            source, symbol, report_date, indicator, value_numeric,
            value_text, currency, unit, fetched_at, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, symbol, report_date, indicator) DO UPDATE SET
            value_numeric=excluded.value_numeric,
            value_text=excluded.value_text,
            currency=excluded.currency,
            unit=excluded.unit,
            fetched_at=excluded.fetched_at,
            raw_json=excluded.raw_json
        """
        values = [
            (
                item.source.lower(), item.symbol.upper(),
                item.report_date.isoformat(), item.indicator.upper(),
                item.value_numeric, item.value_text, item.currency, item.unit,
                item.fetched_at.isoformat(),
                json.dumps(item.raw, ensure_ascii=False, default=str),
            )
            for item in items
        ]
        with self.connect() as connection:
            connection.executemany(sql, values)
        return len(values)

    def query_financial_statement_facts(
        self,
        *,
        source: str = "choice",
        symbols: Iterable[str] | None = None,
        statement_type: str | None = None,
        start_report_date: date | str | None = None,
        end_report_date: date | str | None = None,
    ) -> pd.DataFrame:
        sql = "SELECT * FROM financial_statement_fact WHERE source=?"
        params: list[str] = [source.lower()]
        symbol_list = [str(item).upper() for item in (symbols or [])]
        if symbol_list:
            placeholders = ",".join("?" for _ in symbol_list)
            sql += f" AND symbol IN ({placeholders})"
            params.extend(symbol_list)
        if statement_type is not None:
            if statement_type not in {"income", "balance", "cashflow"}:
                raise ValueError(
                    "statement_type必须是income、balance或cashflow。"
                )
            sql += " AND statement_type=?"
            params.append(statement_type)
        if start_report_date is not None:
            sql += " AND report_date>=?"
            params.append(str(start_report_date))
        if end_report_date is not None:
            sql += " AND report_date<=?"
            params.append(str(end_report_date))
        sql += " ORDER BY symbol, report_date, statement_type, indicator"
        with self.connect() as connection:
            frame = pd.read_sql_query(sql, connection, params=params)
        return frame.drop(columns=["raw_json"], errors="ignore")

    def query_dividend_facts(
        self,
        *,
        source: str = "choice",
        symbols: Iterable[str] | None = None,
        start_report_date: date | str | None = None,
        end_report_date: date | str | None = None,
    ) -> pd.DataFrame:
        sql = "SELECT * FROM dividend_fact WHERE source=?"
        params: list[str] = [source.lower()]
        symbol_list = [str(item).upper() for item in (symbols or [])]
        if symbol_list:
            placeholders = ",".join("?" for _ in symbol_list)
            sql += f" AND symbol IN ({placeholders})"
            params.extend(symbol_list)
        if start_report_date is not None:
            sql += " AND report_date>=?"
            params.append(str(start_report_date))
        if end_report_date is not None:
            sql += " AND report_date<=?"
            params.append(str(end_report_date))
        sql += " ORDER BY symbol, report_date, indicator"
        with self.connect() as connection:
            frame = pd.read_sql_query(sql, connection, params=params)
        return frame.drop(columns=["raw_json"], errors="ignore")

    def log_financial_ingestion(
        self,
        *,
        source: str,
        requested_symbols: list[str],
        requested_report_dates: list[str],
        selected_indicators: dict[str, list[str]],
        rejected_indicators: dict[str, dict[str, str]],
        statement_received_rows: int,
        statement_stored_rows: int,
        dividend_received_rows: int,
        dividend_stored_rows: int,
        errors: dict[str, str],
        started_at: str,
        finished_at: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO financial_ingestion_run (
                    source, requested_symbols, requested_report_dates,
                    selected_indicators, rejected_indicators,
                    statement_received_rows, statement_stored_rows,
                    dividend_received_rows, dividend_stored_rows,
                    errors, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source.lower(),
                    json.dumps(requested_symbols, ensure_ascii=False),
                    json.dumps(requested_report_dates, ensure_ascii=False),
                    json.dumps(selected_indicators, ensure_ascii=False),
                    json.dumps(rejected_indicators, ensure_ascii=False),
                    statement_received_rows, statement_stored_rows,
                    dividend_received_rows, dividend_stored_rows,
                    json.dumps(errors, ensure_ascii=False),
                    started_at, finished_at,
                ),
            )

    def query_financial_ingestion_runs(self) -> pd.DataFrame:
        with self.connect() as connection:
            return pd.read_sql_query(
                "SELECT * FROM financial_ingestion_run ORDER BY run_id",
                connection,
            )

    def log_ingestion(
        self,
        *,
        source: str,
        symbols: list[str],
        start_date: date,
        end_date: date,
        received_rows: int,
        stored_rows: int,
        failed_symbols: dict[str, str],
        started_at: str,
        finished_at: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO ingestion_run (
                    source, requested_symbols, start_date, end_date,
                    received_rows, stored_rows, failed_symbols,
                    started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source,
                    json.dumps(symbols, ensure_ascii=False),
                    start_date.isoformat(),
                    end_date.isoformat(),
                    received_rows,
                    stored_rows,
                    json.dumps(failed_symbols, ensure_ascii=False),
                    started_at,
                    finished_at,
                ),
            )

    def query_daily(
        self,
        symbol: str,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        source: str = "auto",
        adjustment: str = "unadjusted",
    ) -> list[dict]:
        start = str(start_date or "1900-01-01")
        end = str(end_date or "2999-12-31")
        params: list[str] = [symbol.upper(), start, end, adjustment]

        if source != "auto":
            sql = """
            SELECT * FROM daily_bar
            WHERE symbol=? AND trade_date BETWEEN ? AND ?
              AND adjustment=? AND source=?
            ORDER BY trade_date
            """
            params.append(source.lower())
        else:
            priorities = source_priority()
            order_parts = [
                f"WHEN '{name.replace(chr(39), '')}' THEN {index}"
                for index, name in enumerate(priorities, start=1)
            ]
            priority_case = "CASE source " + " ".join(order_parts) + " ELSE 999 END"
            sql = f"""
            WITH ranked AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY symbol, trade_date, adjustment
                    ORDER BY {priority_case}, ingested_at DESC
                ) AS source_rank
                FROM daily_bar
                WHERE symbol=? AND trade_date BETWEEN ? AND ? AND adjustment=?
            )
            SELECT * FROM ranked WHERE source_rank=1 ORDER BY trade_date
            """

        with self.connect() as connection:
            rows = [dict(row) for row in connection.execute(sql, params).fetchall()]
        for row in rows:
            row["date"] = row.pop("trade_date")
            row.pop("raw_json", None)
            row.pop("source_rank", None)
        return rows

    def query_dataframe(self, **kwargs) -> pd.DataFrame:
        return pd.DataFrame(self.query_daily(**kwargs))

    def query_security_master(
        self,
        *,
        source: str = "choice",
        symbols: Iterable[str] | None = None,
    ) -> pd.DataFrame:
        sql = "SELECT * FROM security_master WHERE source=?"
        params: list[str] = [source.lower()]
        symbol_list = [item.upper() for item in (symbols or [])]
        if symbol_list:
            placeholders = ",".join("?" for _ in symbol_list)
            sql += f" AND symbol IN ({placeholders})"
            params.extend(symbol_list)
        sql += " ORDER BY exchange, symbol"
        with self.connect() as connection:
            frame = pd.read_sql_query(sql, connection, params=params)
        if "raw_json" in frame.columns:
            frame = frame.drop(columns=["raw_json"])
        return frame

    def search_security_master(
        self,
        *,
        query: str = "",
        is_symbol: bool = False,
        source: str = "choice",
        exchange: str | None = None,
        asset_type: str | None = None,
        status: str | None = "active",
        limit: int = 100,
    ) -> list[dict]:
        """Search normalized security identities without calling a vendor API."""
        if limit < 1:
            raise ValueError("limit 必须大于0。")

        text = str(query or "").strip()
        normalized = text.upper()
        conditions = ["source=?"]
        params: list[str | int] = [source.lower()]

        if text:
            if is_symbol:
                conditions.append("UPPER(symbol) LIKE ?")
                params.append(f"%{normalized}%")
            else:
                conditions.append("(UPPER(symbol) LIKE ? OR name LIKE ?)")
                params.extend([f"%{normalized}%", f"%{text}%"])

        if exchange and exchange.lower() != "all":
            conditions.append("exchange=?")
            params.append(exchange.upper())
        if asset_type and asset_type.lower() != "all":
            conditions.append("asset_type=?")
            params.append(asset_type.lower())
        if status and status.lower() != "all":
            conditions.append("status=?")
            params.append(status.lower())

        order_sql = "exchange, symbol"
        if text:
            order_sql = """
                CASE
                    WHEN UPPER(symbol)=? THEN 0
                    WHEN name=? THEN 1
                    WHEN UPPER(symbol) LIKE ? THEN 2
                    WHEN name LIKE ? THEN 3
                    ELSE 4
                END,
                symbol
            """
            params.extend([normalized, text, f"{normalized}%", f"{text}%"])

        params.append(limit)
        sql = f"""
            SELECT symbol, name, source, exchange, asset_type, currency,
                   list_date, delist_date, status, as_of_date
            FROM security_master
            WHERE {' AND '.join(conditions)}
            ORDER BY {order_sql}
            LIMIT ?
        """
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(sql, params).fetchall()]

    def query_trading_calendar(
        self,
        *,
        market: str,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        source: str = "choice",
    ) -> pd.DataFrame:
        start = str(start_date or "1900-01-01")
        end = str(end_date or "2999-12-31")
        with self.connect() as connection:
            return pd.read_sql_query(
                """
                SELECT * FROM trading_calendar
                WHERE source=? AND market=? AND trade_date BETWEEN ? AND ?
                ORDER BY trade_date
                """,
                connection,
                params=[source.lower(), market.upper(), start, end],
            )

    def reference_status(self) -> pd.DataFrame:
        with self.connect() as connection:
            return pd.read_sql_query(
                """
                SELECT 'security_master' AS dataset, source,
                       COUNT(*) AS rows,
                       COUNT(DISTINCT symbol) AS entities,
                       MIN(as_of_date) AS first_date,
                       MAX(as_of_date) AS last_date,
                       MAX(fetched_at) AS last_fetched_at
                FROM security_master GROUP BY source
                UNION ALL
                SELECT 'trading_calendar' AS dataset, source,
                       COUNT(*) AS rows,
                       COUNT(DISTINCT market) AS entities,
                       MIN(trade_date) AS first_date,
                       MAX(trade_date) AS last_date,
                       MAX(fetched_at) AS last_fetched_at
                FROM trading_calendar GROUP BY source
                ORDER BY dataset, source
                """,
                connection,
            )

    def source_status(self) -> pd.DataFrame:
        with self.connect() as connection:
            return pd.read_sql_query(
                """
                SELECT source, COUNT(*) AS rows,
                       COUNT(DISTINCT symbol) AS symbols,
                       MIN(trade_date) AS first_date,
                       MAX(trade_date) AS last_date,
                       MAX(ingested_at) AS last_ingested_at
                FROM daily_bar GROUP BY source ORDER BY source
                """,
                connection,
            )
