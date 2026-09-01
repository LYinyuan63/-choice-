"""iFinD official QuantAPI HTTP adapter."""

from __future__ import annotations

import json
import os
from datetime import date

import requests

from qianji_data_mini.adapters.base import AdapterError, DailyBarAdapter
from qianji_data_mini.config import env_float
from qianji_data_mini.models import DailyBar


class IFindAdapter(DailyBarAdapter):
    source = "ifind"

    def __init__(self):
        refresh_token = os.getenv("IFIND_REFRESH_TOKEN", "").strip()
        if not refresh_token:
            raise AdapterError("未设置 IFIND_REFRESH_TOKEN，请先确认 iFinD QuantAPI 权限。")
        token_url = os.getenv(
            "IFIND_ACCESS_TOKEN_URL",
            "https://quantapi.51ifind.com/api/v1/get_access_token",
        )
        response = requests.post(
            token_url,
            headers={"Content-Type": "application/json", "refresh_token": refresh_token},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        self.access_token = (payload.get("data") or {}).get("access_token")
        if not self.access_token:
            raise AdapterError(f"iFinD 未返回 access_token：{str(payload)[:500]}")

    @staticmethod
    def _to_rows(payload: dict, symbol: str) -> list[dict]:
        """Normalize the common QuantAPI table layouts into row dictionaries."""
        tables = payload.get("tables")
        if isinstance(tables, dict):
            tables = [tables]
        if not isinstance(tables, list):
            raise AdapterError(f"iFinD 返回中没有 tables：{json.dumps(payload, ensure_ascii=False)[:800]}")
        result: list[dict] = []
        for table in tables:
            if not isinstance(table, dict):
                continue
            body = table.get("table") if isinstance(table.get("table"), dict) else table
            dates = body.get("time") or body.get("date") or body.get("thscode")
            if not isinstance(dates, list):
                continue
            columns = {
                key.lower(): value
                for key, value in body.items()
                if isinstance(value, list) and len(value) == len(dates)
            }
            for index, value_date in enumerate(dates):
                row = {name: values[index] for name, values in columns.items()}
                row["date"] = str(value_date)[:10]
                row["symbol"] = table.get("thscode") or table.get("code") or symbol
                result.append(row)
        if not result:
            raise AdapterError(
                "iFinD 返回结构与当前解析器不一致，请保存脱敏 JSON 后按本账号版本调整字段映射。"
            )
        return result

    def fetch_daily(self, symbol: str, start_date: date, end_date: date) -> list[DailyBar]:
        history_url = os.getenv(
            "IFIND_HISTORY_URL",
            "https://quantapi.51ifind.com/api/v1/cmd_history_quotation",
        )
        response = requests.post(
            history_url,
            headers={"Content-Type": "application/json", "access_token": self.access_token},
            json={
                "codes": symbol.upper(),
                "indicators": "open,high,low,close,volume,amount,changeRatio,preClose",
                "startdate": start_date.isoformat(),
                "enddate": end_date.isoformat(),
                "functionpara": {"Fill": "Blank"},
            },
            timeout=60,
        )
        response.raise_for_status()
        raw_rows = self._to_rows(response.json(), symbol.upper())
        volume_multiplier = env_float("IFIND_VOLUME_MULTIPLIER", 1)
        amount_multiplier = env_float("IFIND_AMOUNT_MULTIPLIER", 1)
        bars = []
        for row in raw_rows:
            volume = row.get("volume")
            amount = row.get("amount")
            bars.append(
                DailyBar(
                    symbol=str(row.get("symbol") or symbol).upper(),
                    date=row["date"], open=row.get("open"), high=row.get("high"),
                    low=row.get("low"), close=row.get("close"),
                    volume=float(volume) * volume_multiplier if volume not in (None, "") else None,
                    amount=float(amount) * amount_multiplier if amount not in (None, "") else None,
                    previous_close=row.get("preclose"),
                    change_percent=row.get("changeratio"), source=self.source, raw=row,
                )
            )
        return bars

