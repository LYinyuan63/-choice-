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
from qianji_data_mini.models import DailyBar


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

