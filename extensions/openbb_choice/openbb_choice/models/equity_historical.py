"""Choice implementation of OpenBB's EquityHistorical standard model."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from dateutil.relativedelta import relativedelta
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.equity_historical import (
    EquityHistoricalData,
    EquityHistoricalQueryParams,
)
from openbb_core.provider.utils.errors import (
    EmptyDataError,
    OpenBBError,
    UnauthorizedError,
)
from pydantic import Field, ValidationInfo, field_validator

from openbb_choice.utils.emquant import (
    ChoiceAuthenticationError,
    ChoiceClient,
    ChoiceSDKError,
)
from openbb_choice.utils.validators import normalize_choice_symbol_list, validate_iso_date


class ChoiceEquityHistoricalQueryParams(EquityHistoricalQueryParams):
    """Choice historical-price query parameters."""

    __json_schema_extra__ = {
        "symbol": {"multiple_items_allowed": True},
        "period": {"choices": ["daily", "weekly", "monthly"]},
    }

    period: Literal["daily", "weekly", "monthly"] = Field(
        default="daily",
        description="Price frequency: daily, weekly, or monthly.",
    )
    use_cache: bool = Field(
        default=False,
        description=(
            "Reserved for compatibility with the other company providers. "
            "The P0 Choice implementation always requests EmQuantAPI directly."
        ),
    )
    adjustment: Literal["qfq", "hfq"] | None = Field(
        default=None,
        description=(
            "qfq means forward-adjusted (前复权), hfq means backward-adjusted "
            "(后复权), and None means unadjusted."
        ),
    )

    @field_validator("symbol", mode="before", check_fields=False)
    @classmethod
    def normalize_symbol(cls, value: object) -> object:
        """Normalize comma-separated Choice symbols."""
        if value is None:
            return value
        return normalize_choice_symbol_list(str(value))

    @field_validator("start_date", "end_date", mode="before", check_fields=False)
    @classmethod
    def validate_dates(cls, value: object, info: ValidationInfo) -> object:
        """Require ISO dates when the caller supplies strings."""
        return validate_iso_date(value, info.field_name)


class ChoiceEquityHistoricalData(EquityHistoricalData):
    """Choice historical-price record in the OpenBB standard shape."""

    symbol: str = Field(description="Security code with exchange suffix.")
    amount: float | None = Field(default=None, description="Turnover amount in CNY.")
    prev_close: float | None = Field(default=None, description="Previous close price.")
    change: float | None = Field(default=None, description="Close minus previous close.")
    change_percent: float | None = Field(
        default=None,
        description=(
            "Normalized price change. For example, 0.0125 means 1.25 percent."
        ),
        json_schema_extra={
            "x-unit_measurement": "percent",
            "x-frontend_multiply": 100,
        },
    )
    source: Literal["choice"] = "choice"
    volume_unit: Literal["share"] = "share"
    amount_unit: Literal["CNY"] = "CNY"
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"


class ChoiceEquityHistoricalFetcher(
    Fetcher[ChoiceEquityHistoricalQueryParams, list[ChoiceEquityHistoricalData]]
):
    """Fetch historical prices from the locally installed EmQuantAPI SDK."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> ChoiceEquityHistoricalQueryParams:
        """Apply the same one-year default window used by the reference plugins."""
        transformed = dict(params)
        today = date.today()
        transformed.setdefault("start_date", today - relativedelta(years=1))
        transformed.setdefault("end_date", today)
        return ChoiceEquityHistoricalQueryParams(**transformed)

    @staticmethod
    def extract_data(
        query: ChoiceEquityHistoricalQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Login once, request each symbol, then stop the Choice session."""
        try:
            with ChoiceClient(credentials=credentials) as client:
                records = client.historical(
                    symbols=query.symbol.split(","),
                    start_date=query.start_date,
                    end_date=query.end_date,
                    period=query.period,
                    adjustment=query.adjustment,
                )
        except ChoiceAuthenticationError as exc:
            raise UnauthorizedError(str(exc), provider_name="Choice") from exc
        except ChoiceSDKError as exc:
            raise OpenBBError(str(exc)) from exc

        if not records:
            raise EmptyDataError()
        return records

    @staticmethod
    def transform_data(
        query: ChoiceEquityHistoricalQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[ChoiceEquityHistoricalData]:
        """Validate raw dictionaries against the OpenBB data model."""
        return [ChoiceEquityHistoricalData.model_validate(item) for item in data]
