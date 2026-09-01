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

