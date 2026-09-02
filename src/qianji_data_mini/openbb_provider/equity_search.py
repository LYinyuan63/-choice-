"""OpenBB EquitySearch fetcher reading Choice identities from SQLite."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.equity_search import (
    EquitySearchData,
    EquitySearchQueryParams,
)
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field, field_validator

from qianji_data_mini.db import Database


class QianjiEquitySearchQueryParams(EquitySearchQueryParams):
    """Search filters for company-owned security master data."""

    source: Literal["choice"] = Field(
        default="choice",
        description="Original vendor stored in the company database.",
    )
    exchange: Literal["all", "SSE", "SZSE", "BSE"] = Field(
        default="all",
        description="Optional normalized exchange filter.",
    )
    asset_type: Literal["all", "equity", "etf", "fund", "index", "bond"] = Field(
        default="all",
        description="Optional normalized asset type filter.",
    )
    status: Literal["all", "active", "delisted"] = Field(
        default="active",
        description="Listing status filter.",
    )
    limit: int = Field(
        default=100,
        ge=1,
        le=20_000,
        description="Maximum number of matches returned from SQLite.",
    )

    @field_validator("query", mode="before")
    @classmethod
    def strip_query(cls, value: object) -> str:
        """Trim user input while preserving Chinese company names."""
        return str(value or "").strip()


class QianjiEquitySearchData(EquitySearchData):
    """OpenBB search result plus company-standard identity fields."""

    source: Literal["choice"] = "choice"
    exchange: str | None = None
    asset_type: str | None = None
    currency: str | None = None
    list_date: date | None = None
    delist_date: date | None = None
    status: str | None = None
    as_of_date: date | None = None


class QianjiEquitySearchFetcher(
    Fetcher[QianjiEquitySearchQueryParams, list[QianjiEquitySearchData]]
):
    """Search SQLite only; this never logs in to Choice or consumes vendor quota."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> QianjiEquitySearchQueryParams:
        return QianjiEquitySearchQueryParams(**params)

    @staticmethod
    def extract_data(
        query: QianjiEquitySearchQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        del credentials, kwargs
        rows = Database().search_security_master(
            query=query.query,
            is_symbol=query.is_symbol,
            source=query.source,
            exchange=query.exchange,
            asset_type=query.asset_type,
            status=query.status,
            limit=query.limit,
        )
        if not rows:
            raise EmptyDataError()
        return rows

    @staticmethod
    def transform_data(
        query: QianjiEquitySearchQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[QianjiEquitySearchData]:
        del query, kwargs
        return [QianjiEquitySearchData.model_validate(item) for item in data]
