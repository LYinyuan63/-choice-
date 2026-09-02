"""Run the validated Choice CTR financial and dividend ingestion."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from qianji_data_mini import Database, ingest_choice_financial_sample


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env", override=False)


def _csv(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


symbols = _csv(
    "CHOICE_FINANCIAL_SAMPLE_SYMBOLS",
    "000001.SZ,600519.SH,300750.SZ",
)
report_dates = _csv(
    "CHOICE_FINANCIAL_REPORT_DATES",
    "2025-12-31,2026-06-30",
)

result = ingest_choice_financial_sample(
    symbols=symbols,
    report_dates=report_dates,
)
print(result.model_dump_json(indent=2))

print("\n========== 本次运行 ==========")
print(f"本次财务接收/写入：{result.statement_received_rows}/{result.statement_stored_rows}")
print(f"本次分红接收/写入：{result.dividend_received_rows}/{result.dividend_stored_rows}")
print(f"本次错误数量：{len(result.errors)}")

database = Database()
statements = database.query_financial_statement_facts(symbols=symbols)
dividends = database.query_dividend_facts(symbols=symbols)
runs = database.query_financial_ingestion_runs().tail(10)

output_directory = PROJECT_ROOT / "outputs"
output_directory.mkdir(parents=True, exist_ok=True)
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
output_path = output_directory / f"Choice财务分红正式落库_{timestamp}.xlsx"
current_summary = pd.DataFrame(
    [
        {
            "source": result.source,
            "requested_symbols": ",".join(result.requested_symbols),
            "requested_report_dates": ",".join(
                item.isoformat() for item in result.requested_report_dates
            ),
            "statement_received_rows": result.statement_received_rows,
            "statement_stored_rows": result.statement_stored_rows,
            "dividend_received_rows": result.dividend_received_rows,
            "dividend_stored_rows": result.dividend_stored_rows,
            "error_count": len(result.errors),
            "started_at": result.started_at.isoformat(),
            "finished_at": result.finished_at.isoformat(),
        }
    ]
)
current_errors = pd.DataFrame(
    [{"request": key, "error": value} for key, value in result.errors.items()]
)
with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
    current_summary.to_excel(writer, sheet_name="current_run_summary", index=False)
    current_errors.to_excel(writer, sheet_name="current_run_errors", index=False)
    statements.to_excel(writer, sheet_name="financial_statement_fact", index=False)
    dividends.to_excel(writer, sheet_name="dividend_fact", index=False)
    runs.to_excel(writer, sheet_name="ingestion_runs", index=False)

print("\n========== 数据库累计 ==========")
print(f"数据库累计财务事实：{len(statements)}")
print(f"数据库累计分红事实：{len(dividends)}")
print(f"验收文件：{output_path}")
if result.errors:
    quota_limited = any(
        "10001029" in message or "data limit" in message.lower()
        for message in result.errors.values()
    )
    if quota_limited:
        print(
            "\n⚠️ Choice财务数据额度已达到上限。请停止重复运行，"
            "先在Choice官网查询流量或联系账号负责人确认额度与重置周期。"
        )
    raise SystemExit(2)
