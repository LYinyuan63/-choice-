"""Verify that OpenBB can call the installed Choice provider without exposing secrets."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env", override=True)


def main() -> int:
    from openbb import obb

    if "choice" not in obb.coverage.providers:
        raise RuntimeError(
            "OpenBB尚未发现choice Provider。请运行安装Choice_OpenBB插件.bat并重启Python。"
        )

    username = os.getenv("CHOICE_USERNAME", "").strip()
    password = os.getenv("CHOICE_PASSWORD", "")
    if not username or not password:
        raise RuntimeError(".env中缺少CHOICE_USERNAME或CHOICE_PASSWORD。")

    obb.user.credentials.choice_username = username
    obb.user.credentials.choice_password = password

    symbol = os.getenv("VALIDATION_SYMBOLS", "000001.SZ").split(",")[0].strip()
    start_date = os.getenv("VALIDATION_START_DATE", "").strip() or "2026-08-01"
    end_date = os.getenv("VALIDATION_END_DATE", "").strip() or "2026-08-31"

    result = obb.equity.price.historical(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        period="daily",
        use_cache=False,
        provider="choice",
    )
    rows = [item.model_dump(mode="json") for item in result.results]
    output = PROJECT_ROOT / "validation_output"
    output.mkdir(parents=True, exist_ok=True)
    excel_path = output / "Choice_OpenBB真实调用结果.xlsx"
    json_path = output / "Choice_OpenBB真实调用结果.json"
    pd.DataFrame(rows).to_excel(excel_path, index=False)
    json_path.write_text(
        json.dumps(
            {
                "provider": result.provider,
                "symbol": symbol,
                "start_date": start_date,
                "end_date": end_date,
                "row_count": len(rows),
                "results": rows,
                "credentials_included": False,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("Choice OpenBB Provider真实调用完成")
    print(f"provider: {result.provider}")
    print(f"rows: {len(rows)}")
    print(f"Excel: {excel_path}")
    print(f"JSON: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
