"""Choice EmQuantAPI adapter. It intentionally fetches one symbol per call."""

from __future__ import annotations

import os
import re
from datetime import date, datetime

from qianji_data_mini.adapters.base import AdapterError, DailyBarAdapter
from qianji_data_mini.config import env_float
from qianji_data_mini.models import DailyBar


def normalize_choice_date(value: object) -> date:
    """Normalize the date formats returned by different EmQuantAPI versions."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    separated = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
    compact = re.match(r"^(\d{4})(\d{2})(\d{2})$", text)
    matched = separated or compact
    if not matched:
        raise AdapterError(f"Choice 返回了无法识别的日期格式：{value!r}")

    year, month, day = (int(item) for item in matched.groups())
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise AdapterError(f"Choice 返回了无效日期：{value!r}") from exc


class ChoiceAdapter(DailyBarAdapter):
    source = "choice"
    indicators = ["OPEN", "HIGH", "LOW", "CLOSE", "VOLUME", "AMOUNT", "PRECLOSE", "PCTCHANGE"]

    @staticmethod
    def _login_options() -> str:
        """Build EmQuantAPI login options without ever logging credentials."""

        configured = os.getenv(
            "CHOICE_START_OPTIONS",
            "ForceLogin=0,TestLatency=0,RecordLoginInfo=0",
        ).strip()
        mode = os.getenv("CHOICE_LOGIN_MODE", "auto").strip().lower()
        username = os.getenv("CHOICE_USERNAME", "").strip()
        password = os.getenv("CHOICE_PASSWORD", "")

        if mode not in {"auto", "userinfo", "password"}:
            raise AdapterError(
                "CHOICE_LOGIN_MODE 只能填写 auto、userinfo 或 password。"
            )
        if mode == "auto":
            mode = "password" if username or password else "userinfo"

        lowered = configured.replace(" ", "").lower()
        if "forcelogin=1" in lowered and os.getenv("CHOICE_ALLOW_FORCE_LOGIN") != "1":
            raise AdapterError(
                "检测到 ForceLogin=1。若确实需要强制登录，请显式设置 "
                "CHOICE_ALLOW_FORCE_LOGIN=1；日常验证建议保持 ForceLogin=0。"
            )

        if mode == "userinfo":
            return configured

        if not username or not password:
            raise AdapterError(
                "Choice 账密登录需要同时设置 CHOICE_USERNAME 和 CHOICE_PASSWORD。"
            )
        if any(char in username + password for char in [",", "\n", "\r"]):
            raise AdapterError(
                "Choice 账号或密码包含逗号/换行，无法安全放入 options；"
                "请改用 LoginActivator 生成 userInfo，并设置 CHOICE_LOGIN_MODE=userinfo。"
            )
        return f"UserName={username},PassWord={password},{configured}"

    def __init__(self):
        try:
            from EmQuantAPI import c
        except ImportError as exc:
            raise AdapterError(
                "无法导入 EmQuantAPI。请先安装 Choice 官方 Python 接口包并完成激活。"
            ) from exc
        self.c = c
        result = self.c.start(self._login_options())
        error_code = getattr(result, "ErrorCode", result if isinstance(result, int) else -1)
        if error_code != 0:
            error_message = getattr(result, "ErrorMsg", "未返回错误说明")
            raise AdapterError(
                f"Choice 登录失败（错误码 {error_code}）：{error_message}"
            )

    def fetch_daily(self, symbol: str, start_date: date, end_date: date) -> list[DailyBar]:
        response = self.c.csd(
            symbol.upper(),
            ",".join(self.indicators),
            start_date.isoformat(),
            end_date.isoformat(),
            # 与 Tushare daily 保持“不复权”口径，便于双源核对。
            os.getenv(
                "CHOICE_CSD_OPTIONS",
                "period=1,adjustflag=1,curtype=1,order=1",
            ),
        )
        if getattr(response, "ErrorCode", -1) != 0:
            raise AdapterError(f"Choice csd 返回错误：{response}")
        dates = list(getattr(response, "Dates", []) or [])
        indicators = [str(item).upper() for item in (getattr(response, "Indicators", []) or self.indicators)]
        payload = getattr(response, "Data", {})
        values = payload.get(symbol.upper()) if isinstance(payload, dict) else payload
        if values is None:
            raise AdapterError(f"Choice 返回中未找到 {symbol.upper()}：{str(payload)[:500]}")

        # 单代码 csd 常见返回为“指标优先”的扁平数组；也兼容二维数组。
        series: dict[str, list] = {}
        if values and isinstance(values[0], (list, tuple)):
            series = {name.lower(): list(values[i]) for i, name in enumerate(indicators)}
        elif len(values) == len(indicators) * len(dates):
            for i, name in enumerate(indicators):
                series[name.lower()] = list(values[i * len(dates):(i + 1) * len(dates)])
        else:
            raise AdapterError(
                "Choice 返回结构与当前解析器不一致，请把 response.Data 的脱敏结构交给技术人员调整。"
            )

        volume_multiplier = env_float("CHOICE_VOLUME_MULTIPLIER", 1)
        amount_multiplier = env_float("CHOICE_AMOUNT_MULTIPLIER", 1)
        rows = []
        for index, value_date in enumerate(dates):
            raw = {name: items[index] for name, items in series.items()}
            rows.append(
                DailyBar(
                    symbol=symbol.upper(), date=normalize_choice_date(value_date),
                    open=raw.get("open"), high=raw.get("high"), low=raw.get("low"), close=raw.get("close"),
                    volume=raw.get("volume") * volume_multiplier if raw.get("volume") is not None else None,
                    amount=raw.get("amount") * amount_multiplier if raw.get("amount") is not None else None,
                    previous_close=raw.get("preclose"), change_percent=raw.get("pctchange"),
                    source=self.source, raw=raw,
                )
            )
        return rows

    def close(self) -> None:
        try:
            self.c.stop()
        except Exception:
            pass
