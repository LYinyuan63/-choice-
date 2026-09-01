"""OpenBB EquityHistorical fetcher reading from the local database."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.equity_historical import (
    EquityHistoricalData,
    EquityHistoricalQueryParams,
)
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from qianji_data_mini.db import Database


class QianjiEquityHistoricalQueryParams(EquityHistoricalQueryParams):
    source: Literal["auto", "mock", "tushare", "wind", "choice", "ifind"] = Field(
        default="auto",
        description="Stored source to read. auto applies QIANJI_SOURCE_PRIORITY.",
    )


class QianjiEquityHistoricalData(EquityHistoricalData):
    source: str | None = Field(default=None, description="Original vendor source.")
    amount: float | None = Field(default=None, description="Turnover amount in CNY.")
    previous_close: float | None = None
    change_percent: float | None = Field(
        default=None,
        description="Normalized price change; 0.0125 means 1.25 percent.",
        json_schema_extra={
            "x-unit_measurement": "percent",
            "x-frontend_multiply": 100,
        },
    )
    currency: str | None = None
    timezone: str | None = None
    volume_unit: str | None = None
    amount_unit: str | None = None


class QianjiEquityHistoricalFetcher(
    Fetcher[QianjiEquityHistoricalQueryParams, list[QianjiEquityHistoricalData]]
):
    @staticmethod
    def transform_query(params: dict[str, Any]) -> QianjiEquityHistoricalQueryParams:
        today = datetime.now().date()
        transformed = dict(params)
        if not transformed.get("start_date"):
            transformed["start_date"] = today - timedelta(days=365)
        if not transformed.get("end_date"):
            transformed["end_date"] = today
        return QianjiEquityHistoricalQueryParams(**transformed)

    @staticmethod
    def extract_data(
        query: QianjiEquityHistoricalQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        rows = Database().query_daily(
            symbol=query.symbol,
            start_date=query.start_date,
            end_date=query.end_date,
            source=query.source,
            adjustment="unadjusted",
        )
        if not rows:
            raise EmptyDataError()
        return rows

    @staticmethod
    def transform_data(
        query: QianjiEquityHistoricalQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[QianjiEquityHistoricalData]:
        normalized = []
        for row in data:
            item = dict(row)
            # The canonical SQLite layer stores vendor percentage points
            # (for example 1.25 means 1.25%). OpenBB's standard output uses a
            # normalized fraction, so convert only at the consumption boundary.
            if item.get("change_percent") is not None:
                item["change_percent"] = float(item["change_percent"]) / 100
            normalized.append(QianjiEquityHistoricalData.model_validate(item))
        return normalized
