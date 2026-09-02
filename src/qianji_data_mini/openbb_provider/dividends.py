"""OpenBB historical cash-dividend fetcher reading Choice facts from SQLite."""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any, Literal

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.historical_dividends import (
    HistoricalDividendsData,
    HistoricalDividendsQueryParams,
)
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from qianji_data_mini.db import Database


class QianjiHistoricalDividendsQueryParams(HistoricalDividendsQueryParams):
    source: Literal["choice"] = Field(
        default="choice",
        description="Original source stored in the company SQLite database.",
    )


class QianjiHistoricalDividendsData(HistoricalDividendsData):
    report_date: date = Field(description="Reporting period associated with the event.")
    declaration_date: date | None = None
    record_date: date | None = None
    payment_date: date | None = None
    amount_after_tax: float | None = None
    amount_after_tax_text: str | None = None
    dividend_plan: str | None = None
    stock_dividend_ratio: float | None = None
    capitalization_ratio: float | None = None
    share_base_10k: float | None = None
    currency: Literal["CNY"] = "CNY"
    unit: Literal["CNY/share"] = "CNY/share"
    source: Literal["choice"] = "choice"


def _optional_date(value: object) -> date | None:
    if value is None or str(value).strip() in {"", "nan", "None"}:
        return None
    text = str(value).strip()[:10]
    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    raise ValueError(f"无法识别Choice日期：{text!r}")


class QianjiHistoricalDividendsFetcher(
    Fetcher[
        QianjiHistoricalDividendsQueryParams,
        list[QianjiHistoricalDividendsData],
    ]
):
    @staticmethod
    def transform_query(params: dict[str, Any]) -> QianjiHistoricalDividendsQueryParams:
        return QianjiHistoricalDividendsQueryParams(**params)

    @staticmethod
    def extract_data(query, credentials, **kwargs):
        del credentials, kwargs
        frame = Database().query_dividend_facts(
            source=query.source,
            symbols=[query.symbol],
        )
        if frame.empty:
            raise EmptyDataError()
        return frame.to_dict("records")

    @staticmethod
    def transform_data(query, data, **kwargs):
        del kwargs
        periods: dict[str, dict[str, dict[str, object]]] = {}
        for fact in data:
            report_date = str(fact["report_date"])[:10]
            periods.setdefault(report_date, {})[
                str(fact["indicator"]).upper()
            ] = fact

        result: list[QianjiHistoricalDividendsData] = []
        for report_date_text, facts in periods.items():
            ex_date_fact = facts.get("DIVEXDATE", {})
            amount_fact = facts.get("DIVCASHPSBFTAX", {})
            ex_date = _optional_date(ex_date_fact.get("value_text"))
            amount = amount_fact.get("value_numeric")
            if ex_date is None or amount is None:
                continue
            if query.start_date and ex_date < query.start_date:
                continue
            if query.end_date and ex_date > query.end_date:
                continue

            def numeric(indicator: str) -> float | None:
                value = facts.get(indicator, {}).get("value_numeric")
                if value is None:
                    return None
                number = float(value)
                return number if math.isfinite(number) else None

            def text(indicator: str) -> str | None:
                value = facts.get(indicator, {}).get("value_text")
                if value is None or str(value).strip().lower() in {"", "nan", "none"}:
                    return None
                return str(value)

            result.append(
                QianjiHistoricalDividendsData(
                    symbol=query.symbol,
                    report_date=date.fromisoformat(report_date_text),
                    ex_dividend_date=ex_date,
                    amount=float(amount),
                    declaration_date=_optional_date(text("DIVIMPLANNCDATE")),
                    record_date=_optional_date(text("DIVRECORDDATE")),
                    payment_date=_optional_date(text("DIVPAYDATE")),
                    amount_after_tax=numeric("DIVCASHPSAFTAX"),
                    amount_after_tax_text=text("DIVCASHPSAFTAX"),
                    dividend_plan=text("DIVWAY"),
                    stock_dividend_ratio=numeric("DIVSTOCKPSRATIO"),
                    capitalization_ratio=numeric("DIVCAPITPSRATIO"),
                    share_base_10k=numeric("DIVRTISSBASESHARES"),
                )
            )

        if not result:
            raise EmptyDataError()
        return sorted(result, key=lambda item: item.ex_dividend_date, reverse=True)
