"""OpenBB financial statement fetchers reading Choice facts from SQLite."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal, TypeVar

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.balance_sheet import (
    BalanceSheetData,
    BalanceSheetQueryParams,
)
from openbb_core.provider.standard_models.cash_flow import (
    CashFlowStatementData,
    CashFlowStatementQueryParams,
)
from openbb_core.provider.standard_models.income_statement import (
    IncomeStatementData,
    IncomeStatementQueryParams,
)
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field, model_validator

from qianji_data_mini.db import Database


INCOME_FIELDS = {
    "OPERATEREVE": "revenue",
    "NETPROFIT": "consolidated_net_income",
    "PARENTNETPROFIT": "net_income_attributable_to_parent",
}
BALANCE_FIELDS = {
    "SUMASSET": "total_assets",
    "SUMLIAB": "total_liabilities",
    "SUMSHEQUITY": "total_common_equity",
}
CASH_FIELDS = {
    "NETOPERATECASHFLOW": "net_cash_from_operating_activities",
    "NETINVCASHFLOW": "net_cash_from_investing_activities",
    "NETFINACASHFLOW": "net_cash_from_financing_activities",
    "NICASHEQUI": "net_change_in_cash_and_equivalents",
}


class QianjiIncomeStatementQueryParams(IncomeStatementQueryParams):
    """SQLite filters for Choice income statement facts."""

    source: Literal["choice"] = Field(
        default="choice",
        description="Original source stored in the company SQLite database.",
    )
    start_date: date | None = Field(
        default=None,
        description="Earliest reporting period returned from SQLite.",
    )
    end_date: date | None = Field(
        default=None,
        description="Latest reporting period returned from SQLite.",
    )

    @model_validator(mode="after")
    def validate_date_range(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date不能晚于end_date。")
        return self


class QianjiBalanceSheetQueryParams(BalanceSheetQueryParams):
    """SQLite filters for Choice balance sheet facts."""

    source: Literal["choice"] = Field(default="choice")
    start_date: date | None = Field(default=None)
    end_date: date | None = Field(default=None)

    @model_validator(mode="after")
    def validate_date_range(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date不能晚于end_date。")
        return self


class QianjiCashFlowStatementQueryParams(CashFlowStatementQueryParams):
    """SQLite filters for Choice cash-flow statement facts."""

    source: Literal["choice"] = Field(default="choice")
    start_date: date | None = Field(default=None)
    end_date: date | None = Field(default=None)

    @model_validator(mode="after")
    def validate_date_range(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date不能晚于end_date。")
        return self


class QianjiIncomeStatementData(IncomeStatementData):
    symbol: str = Field(description="Company security code.")
    reported_currency: Literal["CNY"] = Field(default="CNY")
    source: Literal["choice"] = Field(default="choice")
    revenue: float | None = Field(default=None, description="Operating revenue in CNY.")
    consolidated_net_income: float | None = Field(
        default=None, description="Consolidated net profit in CNY."
    )
    net_income_attributable_to_parent: float | None = Field(
        default=None,
        description="Net profit attributable to the parent company in CNY.",
    )


class QianjiBalanceSheetData(BalanceSheetData):
    symbol: str = Field(description="Company security code.")
    reported_currency: Literal["CNY"] = Field(default="CNY")
    source: Literal["choice"] = Field(default="choice")
    total_assets: float | None = Field(default=None, description="Total assets in CNY.")
    total_liabilities: float | None = Field(
        default=None, description="Total liabilities in CNY."
    )
    total_common_equity: float | None = Field(
        default=None, description="Total shareholders' equity in CNY."
    )


class QianjiCashFlowStatementData(CashFlowStatementData):
    symbol: str = Field(description="Company security code.")
    reported_currency: Literal["CNY"] = Field(default="CNY")
    source: Literal["choice"] = Field(default="choice")
    net_cash_from_operating_activities: float | None = Field(default=None)
    net_cash_from_investing_activities: float | None = Field(default=None)
    net_cash_from_financing_activities: float | None = Field(default=None)
    net_change_in_cash_and_equivalents: float | None = Field(default=None)


StatementData = TypeVar(
    "StatementData",
    QianjiIncomeStatementData,
    QianjiBalanceSheetData,
    QianjiCashFlowStatementData,
)


def _fiscal_period(report_date: date) -> str:
    return {
        (3, 31): "Q1",
        (6, 30): "Q2",
        (9, 30): "Q3",
        (12, 31): "FY",
    }.get((report_date.month, report_date.day), "FY")


def _extract_statement(
    *,
    symbol: str,
    statement_type: str,
    source: str,
    start_date: date | None,
    end_date: date | None,
) -> list[dict]:
    frame = Database().query_financial_statement_facts(
        source=source,
        symbols=[symbol],
        statement_type=statement_type,
        start_report_date=start_date,
        end_report_date=end_date,
    )
    if frame.empty:
        raise EmptyDataError()
    return frame.to_dict("records")


def _transform_statement(
    *,
    data: list[dict],
    field_map: dict[str, str],
    model: type[StatementData],
    limit: int | None,
) -> list[StatementData]:
    periods: dict[str, dict[str, Any]] = {}
    for fact in data:
        report_date = date.fromisoformat(str(fact["report_date"])[:10])
        period = periods.setdefault(
            report_date.isoformat(),
            {
                "symbol": str(fact["symbol"]).upper(),
                "period_ending": report_date,
                "fiscal_period": _fiscal_period(report_date),
                "fiscal_year": report_date.year,
                "reported_currency": fact.get("currency") or "CNY",
                "source": fact.get("source") or "choice",
            },
        )
        normalized_field = field_map.get(str(fact["indicator"]).upper())
        if normalized_field:
            period[normalized_field] = fact.get("value_numeric")

    rows = [periods[key] for key in sorted(periods, reverse=True)]
    if limit is not None:
        rows = rows[:limit]
    if not rows:
        raise EmptyDataError()
    return [model.model_validate(row) for row in rows]


class QianjiIncomeStatementFetcher(
    Fetcher[QianjiIncomeStatementQueryParams, list[QianjiIncomeStatementData]]
):
    @staticmethod
    def transform_query(params: dict[str, Any]) -> QianjiIncomeStatementQueryParams:
        return QianjiIncomeStatementQueryParams(**params)

    @staticmethod
    def extract_data(query, credentials, **kwargs):
        del credentials, kwargs
        return _extract_statement(
            symbol=query.symbol,
            statement_type="income",
            source=query.source,
            start_date=query.start_date,
            end_date=query.end_date,
        )

    @staticmethod
    def transform_data(query, data, **kwargs):
        del kwargs
        return _transform_statement(
            data=data,
            field_map=INCOME_FIELDS,
            model=QianjiIncomeStatementData,
            limit=query.limit,
        )


class QianjiBalanceSheetFetcher(
    Fetcher[QianjiBalanceSheetQueryParams, list[QianjiBalanceSheetData]]
):
    @staticmethod
    def transform_query(params: dict[str, Any]) -> QianjiBalanceSheetQueryParams:
        return QianjiBalanceSheetQueryParams(**params)

    @staticmethod
    def extract_data(query, credentials, **kwargs):
        del credentials, kwargs
        return _extract_statement(
            symbol=query.symbol,
            statement_type="balance",
            source=query.source,
            start_date=query.start_date,
            end_date=query.end_date,
        )

    @staticmethod
    def transform_data(query, data, **kwargs):
        del kwargs
        return _transform_statement(
            data=data,
            field_map=BALANCE_FIELDS,
            model=QianjiBalanceSheetData,
            limit=query.limit,
        )


class QianjiCashFlowStatementFetcher(
    Fetcher[
        QianjiCashFlowStatementQueryParams,
        list[QianjiCashFlowStatementData],
    ]
):
    @staticmethod
    def transform_query(params: dict[str, Any]) -> QianjiCashFlowStatementQueryParams:
        return QianjiCashFlowStatementQueryParams(**params)

    @staticmethod
    def extract_data(query, credentials, **kwargs):
        del credentials, kwargs
        return _extract_statement(
            symbol=query.symbol,
            statement_type="cashflow",
            source=query.source,
            start_date=query.start_date,
            end_date=query.end_date,
        )

    @staticmethod
    def transform_data(query, data, **kwargs):
        del kwargs
        return _transform_statement(
            data=data,
            field_map=CASH_FIELDS,
            model=QianjiCashFlowStatementData,
            limit=query.limit,
        )
