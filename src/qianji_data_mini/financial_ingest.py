"""Choice small-sample financial statement and dividend ingestion."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

from qianji_data_mini.adapters.choice import ChoiceAdapter
from qianji_data_mini.db import Database
from qianji_data_mini.models import FinancialIngestResult


DEFAULT_INDICATOR_CANDIDATES: dict[str, list[str]] = {
    "income": [
        "TOTALOPERATEREVE",
        "OPERATEREVE",
        "OPERATEPROFIT",
        "TOTALPROFIT",
        "PARENTNETPROFIT",
        "NETPROFIT",
    ],
    "balance": [
        "TOTALASSETS",
        "TOTALLIAB",
        "PARENTNETASSET",
        "TOTALEQUITY",
    ],
    "cashflow": [
        "NETCASHOPERATE",
        "NETCASHINVEST",
        "NETCASHFINANCE",
        "CASHNETI",
    ],
    "dividend": [
        "DIVIDENDPLANEXPLAIN",
        "DIVIDENDPLAN",
        "CASHDIVIDENDPERSHARE",
        "RECORDDATE",
        "EXDIVIDENDDATE",
        "DIVIDENDPAYDATE",
    ],
}


def _as_date(value: date | str) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def _normalized_candidates(
    value: dict[str, Iterable[str]] | None,
) -> dict[str, list[str]]:
    source = value or DEFAULT_INDICATOR_CANDIDATES
    return {
        dataset: list(
            dict.fromkeys(
                str(item).strip().upper()
                for item in source.get(dataset, [])
                if str(item).strip()
            )
        )
        for dataset in ("income", "balance", "cashflow", "dividend")
    }


def ingest_choice_financial_sample(
    *,
    symbols: Iterable[str],
    report_dates: Iterable[date | str],
    indicator_candidates: dict[str, Iterable[str]] | None = None,
    financial_options_template: str = "ReportDate={report_date},type=1",
    dividend_options_template: str = "ReportDate={report_date},PayYear={year}",
    probe_indicators: bool = True,
    database_path: str | Path | None = None,
) -> FinancialIngestResult:
    """Probe accessible indicators, then ingest a bounded real-data sample."""
    symbol_list = list(
        dict.fromkeys(str(item).strip().upper() for item in symbols if str(item).strip())
    )
    dates = sorted(set(_as_date(item) for item in report_dates))
    if not symbol_list:
        raise ValueError("至少需要一个证券代码。")
    if not dates:
        raise ValueError("至少需要一个报告期。")

    candidates = _normalized_candidates(indicator_candidates)
    selected: dict[str, list[str]] = {key: [] for key in candidates}
    rejected: dict[str, dict[str, str]] = {key: {} for key in candidates}
    errors: dict[str, str] = {}
    statement_records = []
    dividend_records = []
    started = datetime.now(timezone.utc)
    database = Database(database_path)
    adapter = ChoiceAdapter()
    try:
        for dataset, indicators in candidates.items():
            options_template = (
                dividend_options_template
                if dataset == "dividend"
                else financial_options_template
            )
            if not probe_indicators:
                selected[dataset] = indicators
                continue
            for indicator in indicators:
                try:
                    valid, message = adapter.probe_css_indicator(
                        symbol=symbol_list[0],
                        report_date=dates[-1],
                        indicator=indicator,
                        options_template=options_template,
                    )
                except Exception as exc:
                    valid = False
                    message = f"{type(exc).__name__}: {exc}"
                if valid:
                    selected[dataset].append(indicator)
                else:
                    rejected[dataset][indicator] = message
            if not selected[dataset]:
                errors[f"indicator_probe:{dataset}"] = (
                    "候选指标全部未通过。请使用Choice命令生成器替换该数据集指标。"
                )

        for report_date in dates:
            for statement_type in ("income", "balance", "cashflow"):
                indicators = selected[statement_type]
                if not indicators:
                    continue
                try:
                    statement_records.extend(
                        adapter.fetch_financial_statement_facts(
                            symbols=symbol_list,
                            report_date=report_date,
                            statement_type=statement_type,
                            indicators=indicators,
                            options_template=financial_options_template,
                        )
                    )
                except Exception as exc:
                    errors[f"{statement_type}:{report_date.isoformat()}"] = (
                        f"{type(exc).__name__}: {exc}"
                    )

            if selected["dividend"]:
                try:
                    dividend_records.extend(
                        adapter.fetch_dividend_facts(
                            symbols=symbol_list,
                            report_date=report_date,
                            indicators=selected["dividend"],
                            options_template=dividend_options_template,
                        )
                    )
                except Exception as exc:
                    errors[f"dividend:{report_date.isoformat()}"] = (
                        f"{type(exc).__name__}: {exc}"
                    )
    finally:
        adapter.close()

    statement_stored = database.upsert_financial_statement_facts(statement_records)
    dividend_stored = database.upsert_dividend_facts(dividend_records)
    finished = datetime.now(timezone.utc)
    database.log_financial_ingestion(
        source="choice",
        requested_symbols=symbol_list,
        requested_report_dates=[item.isoformat() for item in dates],
        selected_indicators=selected,
        rejected_indicators=rejected,
        statement_received_rows=len(statement_records),
        statement_stored_rows=statement_stored,
        dividend_received_rows=len(dividend_records),
        dividend_stored_rows=dividend_stored,
        errors=errors,
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
    )
    return FinancialIngestResult(
        requested_symbols=symbol_list,
        requested_report_dates=dates,
        selected_indicators=selected,
        rejected_indicators=rejected,
        statement_received_rows=len(statement_records),
        statement_stored_rows=statement_stored,
        dividend_received_rows=len(dividend_records),
        dividend_stored_rows=dividend_stored,
        errors=errors,
        started_at=started,
        finished_at=finished,
    )
