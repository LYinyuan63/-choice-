"""Tushare Pro daily-bar adapter."""

from __future__ import annotations

import os
from datetime import date, datetime

from qianji_data_mini.adapters.base import AdapterError, DailyBarAdapter
from qianji_data_mini.models import DailyBar


def number(value):
    if value is None or value != value:
        return None
    return float(value)


class TushareAdapter(DailyBarAdapter):
    source = "tushare"

    def __init__(self):
        token = os.getenv("TUSHARE_TOKEN", "").strip()
        if not token:
            raise AdapterError("未设置 TUSHARE_TOKEN，请复制 .env.example 为 .env 后填写。")
        try:
            import tushare as ts
        except ImportError as exc:
            raise AdapterError("未安装 tushare，请先运行项目安装 Notebook。") from exc
        self.api = ts.pro_api(token)

    def fetch_daily(self, symbol: str, start_date: date, end_date: date) -> list[DailyBar]:
        frame = self.api.daily(
            ts_code=symbol.upper(),
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
        )
        if frame is None or frame.empty:
            return []
        frame = frame.sort_values("trade_date")
        result = []
        for row in frame.to_dict(orient="records"):
            # Tushare A股日线：vol=手，amount=千元。统一转换为股、元。
            result.append(
                DailyBar(
                    symbol=row["ts_code"],
                    date=datetime.strptime(str(row["trade_date"]), "%Y%m%d").date(),
                    open=number(row.get("open")),
                    high=number(row.get("high")),
                    low=number(row.get("low")),
                    close=number(row.get("close")),
                    volume=number(row.get("vol")) * 100 if number(row.get("vol")) is not None else None,
                    amount=number(row.get("amount")) * 1000 if number(row.get("amount")) is not None else None,
                    previous_close=number(row.get("pre_close")),
                    change_percent=number(row.get("pct_chg")),
                    source=self.source,
                    raw=row,
                )
            )
        return result
