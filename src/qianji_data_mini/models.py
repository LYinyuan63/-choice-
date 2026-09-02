"""Canonical data models used by all vendor adapters."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DailyBar(BaseModel):
    """One normalized daily OHLCV record.

    volume is stored in shares, amount in CNY, and change_percent in percentage
    points (for example 1.25 means 1.25%, not 0.0125).
    """

    model_config = ConfigDict(extra="allow")

    symbol: str
    date: date
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None
    amount: float | None = None
    previous_close: float | None = None
    change_percent: float | None = None
    source: str
    currency: str = "CNY"
    timezone: str = "Asia/Shanghai"
    adjustment: str = "unadjusted"
    volume_unit: str = "share"
    amount_unit: str = "CNY"
    raw: dict[str, Any] = Field(default_factory=dict, exclude=True)
    ingested_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @model_validator(mode="after")
    def validate_ohlc(self):
        values = [self.open, self.high, self.low, self.close]
        if all(value is not None for value in values):
            if self.high < max(self.open, self.close, self.low):
                raise ValueError("high is lower than another OHLC value")
            if self.low > min(self.open, self.close, self.high):
                raise ValueError("low is higher than another OHLC value")
        return self


class IngestResult(BaseModel):
    source: str
    requested_symbols: list[str]
    received_rows: int
    stored_rows: int
    failed_symbols: dict[str, str] = Field(default_factory=dict)
    started_at: datetime
    finished_at: datetime


class QuoteSnapshot(BaseModel):
    """One normalized intraday quote snapshot received from a vendor."""

    model_config = ConfigDict(extra="allow")

    symbol: str
    quote_time: datetime
    open: float | None = None
    high: float | None = None
    low: float | None = None
    last_price: float | None = None
    previous_close: float | None = None
    volume: float | None = None
    amount: float | None = None
    source: str = "choice"
    currency: str = "CNY"
    timezone: str = "Asia/Shanghai"
    volume_unit: str = "share"
    amount_unit: str = "CNY"
    raw: dict[str, Any] = Field(default_factory=dict, exclude=True)
    fetched_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @model_validator(mode="after")
    def validate_snapshot(self):
        for field_name in ("open", "high", "low", "last_price"):
            value = getattr(self, field_name)
            if value is not None and value < 0:
                raise ValueError(f"{field_name} cannot be negative")
        if self.volume is not None and self.volume < 0:
            raise ValueError("volume cannot be negative")
        if self.amount is not None and self.amount < 0:
            raise ValueError("amount cannot be negative")
        comparable = [
            value
            for value in (self.open, self.low, self.last_price)
            if value is not None and value > 0
        ]
        if self.high is not None and self.high > 0 and comparable:
            if self.high < max(comparable):
                raise ValueError("high is lower than another positive quote value")
        comparable = [
            value
            for value in (self.open, self.high, self.last_price)
            if value is not None and value > 0
        ]
        if self.low is not None and self.low > 0 and comparable:
            if self.low > min(comparable):
                raise ValueError("low is higher than another positive quote value")
        return self


class QuoteIngestResult(BaseModel):
    """Result of one bounded Choice quote-snapshot ingestion."""

    source: str = "choice"
    requested_symbols: list[str]
    received_rows: int = 0
    stored_rows: int = 0
    errors: dict[str, str] = Field(default_factory=dict)
    started_at: datetime
    finished_at: datetime


class SecurityMaster(BaseModel):
    """One normalized security identity record."""

    symbol: str
    name: str
    exchange: str
    asset_type: str
    currency: str = "CNY"
    list_date: date | None = None
    delist_date: date | None = None
    status: str = "active"
    source: str = "choice"
    as_of_date: date
    raw: dict[str, Any] = Field(default_factory=dict, exclude=True)
    fetched_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class TradingCalendarDay(BaseModel):
    """One calendar date with an explicit market-open flag."""

    market: str
    date: date
    is_open: bool
    previous_open_date: date | None = None
    next_open_date: date | None = None
    source: str = "choice"
    timezone: str = "Asia/Shanghai"
    fetched_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class ReferenceIngestResult(BaseModel):
    """Result of one security-master and trading-calendar ingestion run."""

    source: str = "choice"
    requested_symbols: list[str]
    requested_markets: list[str]
    security_received_rows: int
    security_stored_rows: int
    calendar_received_rows: int
    calendar_stored_rows: int
    errors: dict[str, str] = Field(default_factory=dict)
    started_at: datetime
    finished_at: datetime


class ReferenceRefreshResult(BaseModel):
    """Result of a snapshot-aware Choice reference-data refresh."""

    source: str = "choice"
    universe: str
    snapshot_date: date
    previous_snapshot_date: date | None = None
    current_symbols: list[str]
    current_count: int
    added_symbols: list[str] = Field(default_factory=list)
    removed_symbols: list[str] = Field(default_factory=list)
    modified_symbols: list[str] = Field(default_factory=list)
    unchanged_count: int = 0
    security_received_rows: int = 0
    security_stored_rows: int = 0
    calendar_received_rows: int = 0
    calendar_stored_rows: int = 0
    errors: dict[str, str] = Field(default_factory=dict)
    started_at: datetime
    finished_at: datetime


class FinancialStatementFact(BaseModel):
    """One raw-scale Choice financial statement fact."""

    source: str = "choice"
    symbol: str
    statement_type: str
    report_date: date
    indicator: str
    value_numeric: float | None = None
    value_text: str | None = None
    currency: str = "CNY"
    unit: str = "vendor_raw"
    raw: dict[str, Any] = Field(default_factory=dict, exclude=True)
    fetched_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class DividendFact(BaseModel):
    """One raw-scale Choice dividend indicator for a reporting period."""

    source: str = "choice"
    symbol: str
    report_date: date
    indicator: str
    value_numeric: float | None = None
    value_text: str | None = None
    currency: str = "CNY"
    unit: str = "vendor_raw"
    raw: dict[str, Any] = Field(default_factory=dict, exclude=True)
    fetched_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class FinancialIngestResult(BaseModel):
    """Result of a small-sample Choice financial and dividend ingestion."""

    source: str = "choice"
    requested_symbols: list[str]
    requested_report_dates: list[date]
    selected_indicators: dict[str, list[str]] = Field(default_factory=dict)
    rejected_indicators: dict[str, dict[str, str]] = Field(default_factory=dict)
    statement_received_rows: int = 0
    statement_stored_rows: int = 0
    dividend_received_rows: int = 0
    dividend_stored_rows: int = 0
    errors: dict[str, str] = Field(default_factory=dict)
    started_at: datetime
    finished_at: datetime
