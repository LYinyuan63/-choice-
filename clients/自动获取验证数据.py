"""Run a small Tushare/Choice validation sample from credentials in .env."""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dotenv import load_dotenv  # noqa: E402

from qianji_data_mini.validation import default_date_range, run_validation  # noqa: E402


def split_env(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


def env_date(name: str, default: date) -> date:
    value = os.getenv(name, "").strip()
    return date.fromisoformat(value) if value else default


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env", override=True)
    default_start, default_end = default_date_range()
    start_date = env_date("VALIDATION_START_DATE", default_start)
    end_date = env_date("VALIDATION_END_DATE", default_end)
    sources = split_env("VALIDATION_SOURCES", "tushare,choice")
    symbols = split_env("VALIDATION_SYMBOLS", "000001.SZ,600000.SH")

    print("开始小样本验证（程序不会打印账号、密码或 Token）")
    print(f"数据源：{', '.join(sources)}")
    print(f"证券：{', '.join(symbols)}")
    print(f"日期：{start_date} 至 {end_date}")

    evidence = run_validation(
        sources=sources,
        symbols=symbols,
        start_date=start_date,
        end_date=end_date,
        output_dir=PROJECT_ROOT / "validation_output",
    )
    print("\n验证结果：")
    for item in evidence["results"]:
        print(
            f"- {item['source']}: {item['status']} | "
            f"收到 {item['received_rows']} 条 | 落库 {item['stored_rows']} 条 | "
            f"{item['message']}"
        )
    print(f"\n数据库：{evidence['database']}")
    print(f"Excel证据：{evidence['workbook']}")
    print(f"JSON结果：{evidence['json']}")
    return 0 if any(item["status"] in {"PASS", "PARTIAL"} for item in evidence["results"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
