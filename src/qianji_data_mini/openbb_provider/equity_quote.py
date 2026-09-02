"""OpenBB EquityQuote fetcher reading the latest snapshot from SQLite."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.equity_quote import (
    EquityQuoteData,
    EquityQuoteQueryParams,
)
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field, field_validator

from qianji_data_mini.db import Database


def _normalize_symbols(value: object) -> str:
    symbols = list(
        dict.fromkeys(
            item.strip().upper() for item in str(value).split(",") if item.strip()
        )
    )
    if not symbols:
        raise ValueError("symbol不能为空。")
    return ",".join(symbols)


class QianjiEquityQuoteQueryParams(EquityQuoteQueryParams):
    """SQLite filters for the latest vendor quote snapshot."""

    __json_schema_extra__ = {"symbol": {"multiple_items_allowed": True}}

    source: Literal["choice"] = Field(
        default="choice",
        description="Original source stored in the company SQLite database.",
    )
    use_cache: bool = Field(default=False)

    @field_validator("symbol", mode="before", check_fields=False)
    @classmethod
    def normalize_symbol(cls, value: object) -> str:
        return _normalize_symbols(value)


class QianjiEquityQuoteData(EquityQuoteData):
    """Latest company-database quote with explicit source and units."""

    quote_time: datetime
    amount: float | None = None
    source: Literal["choice"] = "choice"
    currency: Literal["CNY"] = "CNY"
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    volume_unit: Literal["share"] = "share"
    amount_unit: Literal["CNY"] = "CNY"
    fetched_at: datetime


class QianjiEquityQuoteFetcher(
    Fetcher[QianjiEquityQuoteQueryParams, list[QianjiEquityQuoteData]]
):
    """Read the latest stored quote for every requested symbol."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> QianjiEquityQuoteQueryParams:
        return QianjiEquityQuoteQueryParams(**params)

    @staticmethod
    def extract_data(query, credentials, **kwargs):
        del credentials, kwargs
        frame = Database().query_quote_snapshots(
            symbols=query.symbol.split(","),
            source=query.source,
            latest_only=True,
        )
        if frame.empty:
            raise EmptyDataError()
        return frame.to_dict("records")

    @staticmethod
    def transform_data(query, data, **kwargs):
        del query, kwargs
        results = []
        for row in data:
            last_price = row.get("last_price")
            prev_close = row.get("previous_close")
            results.append(
                QianjiEquityQuoteData(
                    symbol=str(row["symbol"]),
                    exchange=str(row["symbol"]).rsplit(".", 1)[-1],
                    last_price=last_price,
                    last_timestamp=row["quote_time"],
                    open=row.get("open"),
                    high=row.get("high"),
                    low=row.get("low"),
                    volume=row.get("volume"),
                    prev_close=prev_close,
                    change=(
                        last_price - prev_close
                        if last_price is not None and prev_close is not None
                        else None
                    ),
                    change_percent=(
                        (last_price - prev_close) / prev_close
                        if last_price is not None and prev_close not in (None, 0)
                        else None
                    ),
                    quote_time=row["quote_time"],
                    amount=row.get("amount"),
                    source=row.get("source") or "choice",
                    currency=row.get("currency") or "CNY",
                    timezone=row.get("timezone") or "Asia/Shanghai",
                    volume_unit=row.get("volume_unit") or "share",
                    amount_unit=row.get("amount_unit") or "CNY",
                    fetched_at=row["fetched_at"],
                )
            )
        return results
