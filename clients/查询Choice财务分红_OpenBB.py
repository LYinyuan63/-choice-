"""Query Choice financial statements and dividends from SQLite through OpenBB.

This client never imports EmQuantAPI and never sends a request to Choice.
Run it only after the qianji provider has been installed and OpenBB rebuilt.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from openbb import obb

from qianji_data_mini import Database


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env", override=False)


def _csv(name: str, default: str) -> list[str]:
    return [item.strip().upper() for item in os.getenv(name, default).split(",") if item.strip()]


def _frame(result) -> pd.DataFrame:
    frame = result.to_dataframe()
    return frame.reset_index(drop=False) if frame.index.name else frame.reset_index(drop=True)


symbols = _csv(
    "QIANJI_OPENBB_FINANCIAL_SYMBOLS",
    os.getenv("CHOICE_FINANCIAL_SAMPLE_SYMBOLS", "000001.SZ,600519.SH,300750.SZ"),
)
start_date = os.getenv("QIANJI_OPENBB_FINANCIAL_START_DATE", "2025-01-01")
end_date = os.getenv("QIANJI_OPENBB_FINANCIAL_END_DATE", "2026-12-31")

database = Database()
run_count_before = len(database.query_financial_ingestion_runs())


routes = {
    "income": obb.equity.fundamental.income,
    "balance": obb.equity.fundamental.balance,
    "cash": obb.equity.fundamental.cash,
    "dividends": obb.equity.fundamental.dividends,
}
frames: dict[str, pd.DataFrame] = {}
errors: list[dict[str, str]] = []

for symbol in symbols:
    for route_name, route in routes.items():
        try:
            result = route(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                source="choice",
                provider="qianji",
                use_cache=False,
            )
            frame = _frame(result)
            frame.insert(0, "query_symbol", symbol)
            frames.setdefault(route_name, pd.DataFrame())
            frames[route_name] = pd.concat(
                [frames[route_name], frame], ignore_index=True
            )
            print(f"PASS {symbol} {route_name}: {len(frame)}行")
        except Exception as exc:  # Keep a complete evidence file for partial coverage.
            message = f"{type(exc).__name__}: {exc}"
            errors.append({"symbol": symbol, "route": route_name, "error": message})
            print(f"FAIL {symbol} {route_name}: {message}")

run_count_after = len(database.query_financial_ingestion_runs())
if run_count_after != run_count_before:
    raise RuntimeError("查询期间出现新的落库运行记录；本客户端应当只读SQLite。")

output_directory = PROJECT_ROOT / "outputs"
output_directory.mkdir(parents=True, exist_ok=True)
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
output_path = output_directory / f"Choice财务分红_OpenBB离线查询_{timestamp}.xlsx"

summary = pd.DataFrame(
    [
        {
            "provider": "qianji",
            "source": "choice",
            "symbols": ",".join(symbols),
            "start_date": start_date,
            "end_date": end_date,
            "income_rows": len(frames.get("income", [])),
            "balance_rows": len(frames.get("balance", [])),
            "cash_rows": len(frames.get("cash", [])),
            "dividend_rows": len(frames.get("dividends", [])),
            "error_count": len(errors),
            "ingestion_runs_unchanged": run_count_after == run_count_before,
        }
    ]
)

with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
    summary.to_excel(writer, sheet_name="summary", index=False)
    pd.DataFrame(errors).to_excel(writer, sheet_name="errors", index=False)
    for route_name, frame in frames.items():
        frame.to_excel(writer, sheet_name=route_name, index=False)

print(f"\n查询完成，不消耗Choice流量。验收文件：{output_path}")
if errors:
    raise SystemExit(2)
