"""Choice implementation of OpenBB's EquityQuote standard model."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.equity_quote import (
    EquityQuoteData,
    EquityQuoteQueryParams,
)
from openbb_core.provider.utils.errors import (
    EmptyDataError,
    OpenBBError,
    UnauthorizedError,
)
from pydantic import Field, field_validator

from openbb_choice.utils.emquant import (
    ChoiceAuthenticationError,
    ChoiceClient,
    ChoiceSDKError,
)
from openbb_choice.utils.validators import normalize_choice_symbol_list


class ChoiceEquityQuoteQueryParams(EquityQuoteQueryParams):
    """Choice quote-snapshot query parameters."""

    __json_schema_extra__ = {"symbol": {"multiple_items_allowed": True}}

    use_cache: bool = Field(
        default=False,
        description="Reserved for compatibility; Choice quotes are requested directly.",
    )

    @field_validator("symbol", mode="before", check_fields=False)
    @classmethod
    def normalize_symbol(cls, value: object) -> object:
        if value is None:
            return value
        return normalize_choice_symbol_list(str(value))


class ChoiceEquityQuoteData(EquityQuoteData):
    """Choice quote with explicit units and source metadata."""

    quote_time: datetime
    amount: float | None = None
    source: Literal["choice"] = "choice"
    currency: Literal["CNY"] = "CNY"
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    volume_unit: Literal["share"] = "share"
    amount_unit: Literal["CNY"] = "CNY"
    fetched_at: datetime


class ChoiceEquityQuoteFetcher(
    Fetcher[ChoiceEquityQuoteQueryParams, list[ChoiceEquityQuoteData]]
):
    """Fetch a bounded one-shot snapshot through EmQuantAPI csqsnapshot."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> ChoiceEquityQuoteQueryParams:
        return ChoiceEquityQuoteQueryParams(**params)

    @staticmethod
    def extract_data(query, credentials, **kwargs):
        del kwargs
        try:
            with ChoiceClient(credentials=credentials) as client:
                records = client.quote_snapshot(symbols=query.symbol.split(","))
        except ChoiceAuthenticationError as exc:
            raise UnauthorizedError(str(exc), provider_name="Choice") from exc
        except ChoiceSDKError as exc:
            raise OpenBBError(str(exc)) from exc
        if not records:
            raise EmptyDataError()
        return records

    @staticmethod
    def transform_data(query, data, **kwargs):
        del query, kwargs
        return [ChoiceEquityQuoteData.model_validate(item) for item in data]
