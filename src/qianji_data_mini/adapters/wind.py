"""WindPy adapter. The official Wind client and Python plug-in must be installed."""

from __future__ import annotations

import os
from datetime import date

from qianji_data_mini.adapters.base import AdapterError, DailyBarAdapter
from qianji_data_mini.config import env_float
from qianji_data_mini.models import DailyBar


class WindAdapter(DailyBarAdapter):
    source = "wind"
    fields = ["OPEN", "HIGH", "LOW", "CLOSE", "VOLUME", "AMT", "PRE_CLOSE", "PCT_CHG"]

    def __init__(self):
        try:
            from WindPy import w
        except ImportError as exc:
            raise AdapterError(
                "无法导入 WindPy。请先在 Wind 终端中安装/配置 Python API，并确认 VS Code 使用同一个 Python。"
            ) from exc
        self.w = w
        start_options = os.getenv("WIND_START_OPTIONS", "")
        started = self.w.start(start_options) if start_options else self.w.start()
        if getattr(started, "ErrorCode", -1) != 0:
            raise AdapterError(f"Wind 登录失败：{started}")

    def fetch_daily(self, symbol: str, start_date: date, end_date: date) -> list[DailyBar]:
        response = self.w.wsd(
            symbol.upper(),
            ",".join(self.fields),
            start_date.isoformat(),
            end_date.isoformat(),
            "PriceAdj=U;Currency=CNY",
        )
        if getattr(response, "ErrorCode", -1) != 0:
            raise AdapterError(f"Wind wsd 返回错误：{response}")
        times = list(getattr(response, "Times", []) or [])
        data = list(getattr(response, "Data", []) or [])
        fields = [str(item).upper() for item in (getattr(response, "Fields", []) or self.fields)]
        if len(data) != len(fields):
            raise AdapterError("Wind 返回结构与预期不同，请检查本机 WindPy 版本和字段权限。")
        volume_multiplier = env_float("WIND_VOLUME_MULTIPLIER", 1)
        amount_multiplier = env_float("WIND_AMOUNT_MULTIPLIER", 1)
        rows = []
        for index, value_date in enumerate(times):
            raw = {field.lower(): data[field_index][index] for field_index, field in enumerate(fields)}
            rows.append(
                DailyBar(
                    symbol=symbol.upper(),
                    date=value_date.date() if hasattr(value_date, "date") else str(value_date)[:10],
                    open=raw.get("open"), high=raw.get("high"), low=raw.get("low"), close=raw.get("close"),
                    volume=raw.get("volume") * volume_multiplier if raw.get("volume") is not None else None,
                    amount=raw.get("amt") * amount_multiplier if raw.get("amt") is not None else None,
                    previous_close=raw.get("pre_close"), change_percent=raw.get("pct_chg"),
                    source=self.source, raw=raw,
                )
            )
        return rows

    def close(self) -> None:
        try:
            self.w.stop()
        except Exception:
            pass

