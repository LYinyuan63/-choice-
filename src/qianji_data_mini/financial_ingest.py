"""Choice official CTR financial statement and dividend ingestion."""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

from qianji_data_mini.adapters.choice import ChoiceAdapter, ChoiceDataLimitError
from qianji_data_mini.db import Database
from qianji_data_mini.models import FinancialIngestResult


# Official fields validated by Notebook 09. The list is deliberately small so
# the first production run remains bounded, reproducible and easy to audit.
DEFAULT_CTR_FIELDS: dict[str, list[str]] = {
    "income": ["OPERATEREVE", "NETPROFIT", "PARENTNETPROFIT"],
    "balance": ["SUMASSET", "SUMLIAB", "SUMSHEQUITY"],
    "cashflow": [
        "NETOPERATECASHFLOW",
        "NETINVCASHFLOW",
        "NETFINACASHFLOW",
        "NICASHEQUI",
    ],
    "dividend": [
        "DIVWAY",
        "DIVCASHPSBFTAX",
        "DIVCASHPSAFTAX",
        "DIVSTOCKPSRATIO",
        "DIVCAPITPSRATIO",
        "DIVRTISSBASESHARES",
        "SHAREBASEDATE",
        "DIVIMPLANNCDATE",
        "DIVRECORDDATE",
        "DIVEXDATE",
        "DIVPAYDATE",
    ],
}

# Backward-compatible import name used by early notebooks.
DEFAULT_INDICATOR_CANDIDATES = DEFAULT_CTR_FIELDS


def _as_date(value: date | str) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def _normalized_fields(
    value: dict[str, Iterable[str]] | None,
) -> dict[str, list[str]]:
    environment_names = {
        "income": "CHOICE_CTR_INCOME_FIELDS",
        "balance": "CHOICE_CTR_BALANCE_FIELDS",
        "cashflow": "CHOICE_CTR_CASHFLOW_FIELDS",
        "dividend": "CHOICE_CTR_DIVIDEND_FIELDS",
    }
    source = value or {
        dataset: os.getenv(environment_names[dataset], ",".join(defaults)).split(",")
        for dataset, defaults in DEFAULT_CTR_FIELDS.items()
    }
    normalized = {
        dataset: list(
            dict.fromkeys(
                str(item).strip().upper()
                for item in source.get(dataset, [])
                if str(item).strip()
            )
        )
        for dataset in ("income", "balance", "cashflow", "dividend")
    }
    empty = [dataset for dataset, fields in normalized.items() if not fields]
    if empty:
        raise ValueError(f"以下数据集没有配置CTR字段：{','.join(empty)}。")
    return normalized


def ingest_choice_financial_sample(
    *,
    symbols: Iterable[str],
    report_dates: Iterable[date | str],
    indicator_candidates: dict[str, Iterable[str]] | None = None,
    report_type: int | None = None,
    database_path: str | Path | None = None,
) -> FinancialIngestResult:
    """Ingest a bounded Choice sample through official CTR report commands.

    Each statement is requested per symbol and period, so one permission or
    data error does not discard the other evidence. Dividends are requested
    once per symbol over the complete report-period range.
    """
    symbol_list = list(
        dict.fromkeys(str(item).strip().upper() for item in symbols if str(item).strip())
    )
    dates = sorted(set(_as_date(item) for item in report_dates))
    if not symbol_list:
        raise ValueError("至少需要一个证券代码。")
    if not dates:
        raise ValueError("至少需要一个报告期。")
    actual_report_type = (
        int(os.getenv("CHOICE_CTR_REPORT_TYPE", "1"))
        if report_type is None
        else report_type
    )
    if actual_report_type not in {1, 2, 3, 4}:
        raise ValueError("report_type必须是1、2、3或4。")

    selected = _normalized_fields(indicator_candidates)
    rejected: dict[str, dict[str, str]] = {key: {} for key in selected}
    errors: dict[str, str] = {}
    statement_records = []
    dividend_records = []
    started = datetime.now(timezone.utc)
    database = Database(database_path)
    adapter = ChoiceAdapter()
    try:
        statement_tasks = [
            (symbol, report_date, statement_type)
            for symbol in symbol_list
            for report_date in dates
            for statement_type in ("income", "balance", "cashflow")
        ]
        for task_index, (symbol, report_date, statement_type) in enumerate(
            statement_tasks, start=1
        ):
            request_key = f"{statement_type}:{symbol}:{report_date.isoformat()}"
            try:
                statement_records.extend(
                    adapter.fetch_financial_statement_facts(
                        symbols=[symbol],
                        report_date=report_date,
                        statement_type=statement_type,
                        indicators=selected[statement_type],
                        report_type=actual_report_type,
                    )
                )
            except ChoiceDataLimitError as exc:
                errors[request_key] = f"{type(exc).__name__}: {exc}"
                skipped = len(statement_tasks) - task_index
                errors["financial_quota_circuit_breaker"] = (
                    "检测到Choice财务数据额度上限，已停止后续财务请求，"
                    f"避免连续无效调用；本次跳过{skipped}个财务请求。"
                )
                break
            except Exception as exc:
                errors[request_key] = f"{type(exc).__name__}: {exc}"

        for symbol in symbol_list:
            try:
                dividend_records.extend(
                    adapter.fetch_dividend_facts(
                        symbols=[symbol],
                        report_dates=dates,
                        indicators=selected["dividend"],
                    )
                )
            except Exception as exc:
                errors[
                    f"dividend:{symbol}:{dates[0].isoformat()}:{dates[-1].isoformat()}"
                ] = f"{type(exc).__name__}: {exc}"
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
