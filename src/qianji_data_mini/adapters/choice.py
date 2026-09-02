"""Choice EmQuantAPI adapter. It intentionally fetches one symbol per call."""

from __future__ import annotations

import os
import re
from bisect import bisect_left, bisect_right
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import pandas as pd

from qianji_data_mini.adapters.base import AdapterError, DailyBarAdapter
from qianji_data_mini.config import env_float
from qianji_data_mini.models import (
    DailyBar,
    DividendFact,
    FinancialStatementFact,
    QuoteSnapshot,
    SecurityMaster,
    TradingCalendarDay,
)


def normalize_choice_date(value: object) -> date:
    """Normalize the date formats returned by different EmQuantAPI versions."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    separated = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
    compact = re.match(r"^(\d{4})(\d{2})(\d{2})$", text)
    month_first = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", text)
    matched = separated or compact
    if matched:
        year, month, day = (int(item) for item in matched.groups())
    elif month_first:
        month, day, year = (int(item) for item in month_first.groups())
    else:
        raise AdapterError(f"Choice 返回了无法识别的日期格式：{value!r}")
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise AdapterError(f"Choice 返回了无效日期：{value!r}") from exc


def normalize_choice_optional_date(value: object) -> date | None:
    """Normalize optional Choice dates without turning placeholders into dates."""
    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    if str(value).strip() in {"", "--", "None", "null", "NULL", "0"}:
        return None
    return normalize_choice_date(value)


def _flatten_values(value: object) -> list[object]:
    if isinstance(value, dict):
        flattened: list[object] = []
        for item in value.values():
            flattened.extend(_flatten_values(item))
        return flattened
    if isinstance(value, (list, tuple, set)):
        flattened = []
        for item in value:
            flattened.extend(_flatten_values(item))
        return flattened
    return [value]


def _exchange_from_symbol(symbol: str) -> str:
    suffix = symbol.upper().rsplit(".", 1)[-1]
    return {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}.get(suffix, suffix)


def _asset_type_from_symbol(symbol: str) -> str:
    code, _, suffix = symbol.upper().partition(".")
    if (suffix == "SH" and code.startswith("5")) or (
        suffix == "SZ" and code.startswith(("15", "16"))
    ):
        return "etf"
    return "equity"


def _fact_value(value: object) -> tuple[float | None, str | None]:
    """Preserve vendor values while extracting a safe numeric representation."""
    if value is None:
        return None, None
    try:
        if bool(pd.isna(value)):
            return None, None
    except (TypeError, ValueError):
        pass
    if str(value).strip() in {"", "--", "None", "null", "NULL"}:
        return None, None
    if isinstance(value, bool):
        return float(value), str(value)
    if isinstance(value, (int, float)):
        number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            return None, str(value)
        return number, str(value)
    text = str(value).strip()
    try:
        number = float(text.replace(",", ""))
    except ValueError:
        number = None
    return number, text or None


def _format_options(template: str, report_date: date) -> str:
    return template.format(
        report_date=report_date.isoformat(),
        report_date_compact=report_date.strftime("%Y%m%d"),
        year=report_date.year,
    )


CHOICE_CTR_REPORTS: dict[str, str] = {
    "income": "IncomeStatementSHSZ",
    "balance": "BalanceStatementSHSZ",
    "cashflow": "CashFlowStatementSHSZ",
}

CHOICE_DIVIDEND_CTR = "DividendImplementationInfo"

CHOICE_DIVIDEND_UNITS: dict[str, str] = {
    "DIVWAY": "text",
    "DIVCASHPSBFTAX": "CNY/share",
    "DIVCASHPSAFTAX": "CNY/share",
    "DIVSTOCKPSRATIO": "vendor_raw_ratio",
    "DIVCAPITPSRATIO": "vendor_raw_ratio",
    "DIVRTISSBASESHARES": "10k_share",
    "SHAREBASEDATE": "date",
    "DIVIMPLANNCDATE": "date",
    "DIVRECORDDATE": "date",
    "DIVEXDATE": "date",
    "DIVPAYDATE": "date",
}


class ChoiceDataLimitError(AdapterError):
    """Choice account-side data quota or flow allowance is exhausted."""


class ChoiceAdapter(DailyBarAdapter):
    source = "choice"
    indicators = ["OPEN", "HIGH", "LOW", "CLOSE", "VOLUME", "AMOUNT", "PRECLOSE", "PCTCHANGE"]
    quote_indicators = [
        "TIME", "PRECLOSE", "OPEN", "HIGH", "LOW", "NOW", "VOLUME", "AMOUNT"
    ]

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

    @staticmethod
    def _quote_time(value: object, received_at: datetime) -> datetime:
        """Normalize Choice snapshot timestamps to Asia/Shanghai."""
        market_tz = ZoneInfo("Asia/Shanghai")
        if isinstance(value, datetime):
            return value.replace(tzinfo=market_tz) if value.tzinfo is None else value.astimezone(market_tz)
        if isinstance(value, time):
            return datetime.combine(received_at.astimezone(market_tz).date(), value, market_tz)

        text = str(value or "").strip()
        patterns = (
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y/%m/%d %H:%M",
            "%H:%M:%S",
            "%H:%M",
            "%H%M%S",
        )
        for pattern in patterns:
            try:
                parsed = datetime.strptime(text, pattern)
            except ValueError:
                continue
            if pattern.startswith("%H"):
                parsed = datetime.combine(
                    received_at.astimezone(market_tz).date(), parsed.time()
                )
            return parsed.replace(tzinfo=market_tz)
        return received_at.astimezone(market_tz)

    def fetch_quote_snapshots(
        self,
        *,
        symbols: Iterable[str],
    ) -> list[QuoteSnapshot]:
        """Fetch one non-streaming Choice quote snapshot for multiple symbols."""
        symbol_list = list(
            dict.fromkeys(
                str(item).strip().upper() for item in symbols if str(item).strip()
            )
        )
        if not symbol_list:
            raise ValueError("实时行情至少需要一个证券代码。")
        options = os.getenv("CHOICE_CSQSNAPSHOT_OPTIONS", "Ispandas=0").strip()
        response = self.c.csqsnapshot(
            ",".join(symbol_list),
            ",".join(self.quote_indicators),
            options,
        )
        error_code = getattr(response, "ErrorCode", -1)
        if error_code != 0:
            error_message = getattr(response, "ErrorMsg", "未返回错误说明")
            if str(error_code) == "10001029" or "data limit exceeded" in str(
                error_message
            ).lower():
                raise ChoiceDataLimitError(
                    "Choice实时行情额度已达到上限（10001029: data limit exceeded）。"
                )
            raise AdapterError(
                f"Choice csqsnapshot 返回错误（{error_code}）：{error_message}"
            )

        indicators = [
            str(item).upper()
            for item in (
                getattr(response, "Indicators", []) or self.quote_indicators
            )
        ]
        payload = getattr(response, "Data", {})
        if not isinstance(payload, dict):
            raise AdapterError("Choice csqsnapshot 返回的Data不是按证券代码组织的字典。")

        received_at = datetime.now(timezone.utc)
        volume_multiplier = env_float("CHOICE_VOLUME_MULTIPLIER", 1)
        amount_multiplier = env_float("CHOICE_AMOUNT_MULTIPLIER", 1)
        records: list[QuoteSnapshot] = []
        for symbol in symbol_list:
            values = payload.get(symbol)
            if values is None:
                values = payload.get(symbol.upper())
            if values is None:
                raise AdapterError(f"Choice csqsnapshot 未返回 {symbol}。")
            if isinstance(values, (list, tuple)) and len(values) == 1 and isinstance(
                values[0], (list, tuple)
            ):
                values = values[0]
            values = list(values) if isinstance(values, (list, tuple)) else [values]
            if len(values) != len(indicators):
                raise AdapterError(
                    f"Choice csqsnapshot 字段数不匹配：{symbol}，"
                    f"Indicators={len(indicators)}，Values={len(values)}。"
                )
            raw = dict(zip(indicators, values))
            quote_time = self._quote_time(raw.get("TIME"), received_at)
            records.append(
                QuoteSnapshot(
                    symbol=symbol,
                    quote_time=quote_time,
                    open=_fact_value(raw.get("OPEN"))[0],
                    high=_fact_value(raw.get("HIGH"))[0],
                    low=_fact_value(raw.get("LOW"))[0],
                    last_price=_fact_value(raw.get("NOW"))[0],
                    previous_close=_fact_value(raw.get("PRECLOSE"))[0],
                    volume=(
                        _fact_value(raw.get("VOLUME"))[0] * volume_multiplier
                        if _fact_value(raw.get("VOLUME"))[0] is not None
                        else None
                    ),
                    amount=(
                        _fact_value(raw.get("AMOUNT"))[0] * amount_multiplier
                        if _fact_value(raw.get("AMOUNT"))[0] is not None
                        else None
                    ),
                    raw=raw,
                    fetched_at=received_at,
                )
            )
        return records

    @staticmethod
    def _parse_css_response(response: Any, symbols: list[str]) -> list[tuple[str, dict[str, Any]]]:
        indicators = [
            str(item).upper()
            for item in (getattr(response, "Indicators", []) or [])
        ]
        payload = getattr(response, "Data", {})
        if not indicators:
            raise AdapterError("Choice css 未返回 Indicators。")

        parsed: list[tuple[str, dict[str, Any]]] = []
        if isinstance(payload, dict):
            for symbol in symbols:
                values = payload.get(symbol)
                if values is None:
                    values = payload.get(symbol.upper())
                if values is None:
                    raise AdapterError(f"Choice css 未返回 {symbol} 的主数据。")
                if isinstance(values, (list, tuple)) and len(values) == 1 and isinstance(values[0], (list, tuple)):
                    values = values[0]
                values = list(values) if isinstance(values, (list, tuple)) else [values]
                if len(values) != len(indicators):
                    raise AdapterError(
                        f"Choice css 返回字段数不匹配：{symbol}，"
                        f"Indicators={len(indicators)}，Data={len(values)}。"
                    )
                parsed.append((symbol, dict(zip(indicators, values))))
            return parsed

        values = list(payload or [])
        expected = len(symbols) * len(indicators)
        if len(values) != expected:
            raise AdapterError(
                f"Choice css 返回结构无法识别：期望{expected}个值，实际{len(values)}个。"
            )
        for index, symbol in enumerate(symbols):
            start = index * len(indicators)
            parsed.append(
                (symbol, dict(zip(indicators, values[start:start + len(indicators)])))
            )
        return parsed

    def fetch_sector_symbols(
        self,
        *,
        sector_code: str = "001004",
        as_of_date: date,
    ) -> list[str]:
        """Fetch a Choice sector constituent list; 001004 is all A shares."""
        response = self.c.sector(sector_code, as_of_date.isoformat())
        if getattr(response, "ErrorCode", -1) != 0:
            raise AdapterError(
                f"Choice sector 返回错误（{getattr(response, 'ErrorCode', -1)}）："
                f"{getattr(response, 'ErrorMsg', '未返回错误说明')}"
            )
        symbols = []
        for item in _flatten_values(getattr(response, "Data", []) or []):
            text = str(item).strip().upper()
            if re.match(r"^[0-9A-Z]+\.(SH|SZ|BJ)$", text):
                symbols.append(text)
        unique = list(dict.fromkeys(symbols))
        if not unique:
            raise AdapterError(f"Choice sector {sector_code} 未返回可识别证券代码。")
        return unique

    def fetch_security_master(
        self,
        *,
        symbols: Iterable[str],
        as_of_date: date,
        batch_size: int = 100,
    ) -> list[SecurityMaster]:
        """Fetch normalized identity records with permission-tolerant indicators."""
        symbol_list = list(
            dict.fromkeys(str(item).strip().upper() for item in symbols if str(item).strip())
        )
        if not symbol_list:
            raise ValueError("证券主数据至少需要一个证券代码。")
        if batch_size < 1:
            raise ValueError("batch_size 必须大于0。")

        configured = os.getenv(
            "CHOICE_MASTER_INDICATORS",
            "NAME,LISTDATE,DELISTDATE",
        ).strip()
        indicator_candidates = list(
            dict.fromkeys(
                item for item in [configured, "NAME,LISTDATE", "NAME"] if item
            )
        )
        css_options = os.getenv("CHOICE_MASTER_CSS_OPTIONS", "").strip()
        records: list[SecurityMaster] = []

        for offset in range(0, len(symbol_list), batch_size):
            chunk = symbol_list[offset:offset + batch_size]
            parsed_rows: list[tuple[str, dict[str, Any]]] | None = None
            attempt_errors = []
            for indicators in indicator_candidates:
                response = self.c.css(
                    ",".join(chunk),
                    indicators,
                    css_options,
                )
                if getattr(response, "ErrorCode", -1) != 0:
                    attempt_errors.append(
                        f"{indicators}: ErrorCode={getattr(response, 'ErrorCode', -1)} "
                        f"{getattr(response, 'ErrorMsg', '未返回错误说明')}"
                    )
                    continue
                try:
                    parsed_rows = self._parse_css_response(response, chunk)
                    break
                except AdapterError as exc:
                    attempt_errors.append(f"{indicators}: {exc}")

            if parsed_rows is None:
                raise AdapterError(
                    "Choice证券主数据css调用全部失败；请在Choice命令生成器确认指标权限。"
                    + " | ".join(attempt_errors)
                )

            for symbol, raw in parsed_rows:
                name_value = raw.get("NAME")
                name = str(name_value).strip() if name_value not in (None, "", "--") else symbol
                list_date = normalize_choice_optional_date(raw.get("LISTDATE"))
                delist_date = normalize_choice_optional_date(raw.get("DELISTDATE"))
                status = (
                    "delisted"
                    if delist_date is not None and delist_date <= as_of_date
                    else "active"
                )
                raw_with_meta = dict(raw)
                raw_with_meta["_name_source"] = "choice" if name != symbol else "symbol_fallback"
                raw_with_meta["_available_indicators"] = sorted(raw)
                records.append(
                    SecurityMaster(
                        symbol=symbol,
                        name=name,
                        exchange=_exchange_from_symbol(symbol),
                        asset_type=_asset_type_from_symbol(symbol),
                        currency="CNY",
                        list_date=list_date,
                        delist_date=delist_date,
                        status=status,
                        source=self.source,
                        as_of_date=as_of_date,
                        raw=raw_with_meta,
                    )
                )
        return records

    def fetch_trading_calendar(
        self,
        *,
        market: str,
        start_date: date,
        end_date: date,
    ) -> list[TradingCalendarDay]:
        """Fetch open dates and expand them into an explicit daily calendar."""
        if start_date > end_date:
            raise ValueError("start_date 不能晚于 end_date。")
        market_code = market.strip().upper()
        options = f"Period=1,Order=1,Market={market_code}"
        response = self.c.tradedates(
            start_date.isoformat(),
            end_date.isoformat(),
            options,
        )
        if getattr(response, "ErrorCode", -1) != 0:
            raise AdapterError(
                f"Choice tradedates {market_code} 返回错误"
                f"（{getattr(response, 'ErrorCode', -1)}）："
                f"{getattr(response, 'ErrorMsg', '未返回错误说明')}"
            )

        open_dates = sorted(
            {
                normalize_choice_date(item)
                for item in _flatten_values(getattr(response, "Data", []) or [])
                if item not in (None, "", "--")
            }
        )
        open_dates = [item for item in open_dates if start_date <= item <= end_date]
        if not open_dates:
            raise AdapterError(
                f"Choice tradedates {market_code} 在指定范围内未返回交易日。"
            )
        open_set = set(open_dates)
        records = []
        current = start_date
        while current <= end_date:
            previous_index = bisect_left(open_dates, current) - 1
            next_index = bisect_right(open_dates, current)
            records.append(
                TradingCalendarDay(
                    market=market_code,
                    date=current,
                    is_open=current in open_set,
                    previous_open_date=(
                        open_dates[previous_index] if previous_index >= 0 else None
                    ),
                    next_open_date=(
                        open_dates[next_index] if next_index < len(open_dates) else None
                    ),
                    source=self.source,
                )
            )
            current += timedelta(days=1)
        return records

    @staticmethod
    def _ctr_dataframe(
        response: Any,
        *,
        ctr_name: str,
        required_fields: Iterable[str],
    ) -> pd.DataFrame:
        """Validate and normalize a Choice CTR pandas response."""
        if not isinstance(response, pd.DataFrame):
            error_code = getattr(response, "ErrorCode", -1)
            error_message = getattr(response, "ErrorMsg", "未返回错误说明")
            if str(error_code) == "10001029" or "data limit exceeded" in str(
                error_message
            ).lower():
                raise ChoiceDataLimitError(
                    "Choice数据额度已达到上限（10001029: data limit exceeded）。"
                )
            raise AdapterError(
                f"Choice ctr {ctr_name} 返回错误"
                f"（{error_code}）：{error_message}"
            )
        frame = response.copy()
        frame.columns = [str(column).strip().upper() for column in frame.columns]
        if frame.empty:
            raise AdapterError(f"Choice ctr {ctr_name} 请求成功但报表为空。")
        missing = [
            str(field).upper()
            for field in required_fields
            if str(field).upper() not in frame.columns
        ]
        if missing:
            raise AdapterError(
                f"Choice ctr {ctr_name} 缺少字段：{','.join(missing)}。"
            )
        return frame

    def fetch_financial_statement_facts(
        self,
        *,
        symbols: Iterable[str],
        report_date: date,
        statement_type: str,
        indicators: Iterable[str],
        report_type: int = 1,
    ) -> list[FinancialStatementFact]:
        """Fetch one reporting period through the official Choice CTR reports."""
        symbol_list = list(
            dict.fromkeys(str(item).strip().upper() for item in symbols if str(item).strip())
        )
        indicator_list = list(
            dict.fromkeys(str(item).strip().upper() for item in indicators if str(item).strip())
        )
        if statement_type not in {"income", "balance", "cashflow"}:
            raise ValueError("statement_type必须是income、balance或cashflow。")
        if report_type not in {1, 2, 3, 4}:
            raise ValueError("report_type必须是1、2、3或4。")
        if not symbol_list or not indicator_list:
            return []
        ctr_name = CHOICE_CTR_REPORTS[statement_type]
        records: list[FinancialStatementFact] = []
        for symbol in symbol_list:
            fields = ["REPORTDATE", *indicator_list]
            options = (
                f"SecuCode={symbol},ReportDate={report_date.isoformat()},"
                f"ReportType={report_type},RECVtimeout=60,Ispandas=1"
            )
            response = self.c.ctr(ctr_name, ",".join(fields), options)
            frame = self._ctr_dataframe(
                response,
                ctr_name=ctr_name,
                required_fields=fields,
            )
            returned_dates = frame["REPORTDATE"].map(normalize_choice_optional_date)
            matched = frame.loc[returned_dates == report_date]
            if matched.empty:
                available = sorted(
                    item.isoformat() for item in returned_dates.dropna().unique()
                )
                raise AdapterError(
                    f"Choice ctr {ctr_name} 未返回请求报告期"
                    f" {report_date.isoformat()}；实际报告期：{available}。"
                )
            row = matched.iloc[-1]
            raw_row = {str(key): value for key, value in row.to_dict().items()}
            for indicator in indicator_list:
                value = row[indicator]
                numeric, text = _fact_value(value)
                records.append(
                    FinancialStatementFact(
                        symbol=symbol,
                        statement_type=statement_type,
                        report_date=report_date,
                        indicator=indicator,
                        value_numeric=numeric,
                        value_text=text,
                        currency="CNY",
                        unit="CNY",
                        raw={"ctr_name": ctr_name, "row": raw_row},
                    )
                )
        return records

    def fetch_dividend_facts(
        self,
        *,
        symbols: Iterable[str],
        report_dates: Iterable[date],
        indicators: Iterable[str],
    ) -> list[DividendFact]:
        """Fetch implemented dividends using report-period filtering (DateType=3)."""
        symbol_list = list(
            dict.fromkeys(str(item).strip().upper() for item in symbols if str(item).strip())
        )
        date_list = sorted(set(report_dates))
        indicator_list = list(
            dict.fromkeys(str(item).strip().upper() for item in indicators if str(item).strip())
        )
        if not symbol_list or not date_list or not indicator_list:
            return []
        records: list[DividendFact] = []
        requested_dates = set(date_list)
        for symbol in symbol_list:
            fields = ["SECUCODE", "REPORTDATE", *indicator_list]
            options = (
                f"secucode={symbol},StartDate={date_list[0].isoformat()},"
                f"EndDate={date_list[-1].isoformat()},DateType=3,"
                "RECVtimeout=60,Ispandas=1"
            )
            response = self.c.ctr(
                CHOICE_DIVIDEND_CTR,
                ",".join(fields),
                options,
            )
            if isinstance(response, pd.DataFrame) and response.empty:
                continue
            frame = self._ctr_dataframe(
                response,
                ctr_name=CHOICE_DIVIDEND_CTR,
                required_fields=fields,
            )
            frame["_REPORT_DATE"] = frame["REPORTDATE"].map(
                normalize_choice_optional_date
            )
            frame = frame[frame["_REPORT_DATE"].isin(requested_dates)].copy()
            if frame.empty:
                continue
            if "DIVIMPLANNCDATE" in frame.columns:
                frame["_SORT_DATE"] = frame["DIVIMPLANNCDATE"].map(
                    normalize_choice_optional_date
                )
                frame["_SORT_DATE"] = frame["_SORT_DATE"].map(
                    lambda value: value.isoformat() if value else ""
                )
                frame = frame.sort_values("_SORT_DATE", na_position="first")
            frame = frame.drop_duplicates("_REPORT_DATE", keep="last")

            for _, row in frame.iterrows():
                actual_report_date = row["_REPORT_DATE"]
                if actual_report_date is None:
                    continue
                raw_row = {
                    str(key): value
                    for key, value in row.drop(
                        labels=["_REPORT_DATE", "_SORT_DATE"], errors="ignore"
                    ).to_dict().items()
                }
                for indicator in indicator_list:
                    value = row[indicator]
                    unit = CHOICE_DIVIDEND_UNITS.get(indicator, "vendor_raw")
                    if unit == "date":
                        normalized = normalize_choice_optional_date(value)
                        numeric = None
                        text = normalized.isoformat() if normalized else _fact_value(value)[1]
                    else:
                        numeric, text = _fact_value(value)
                    records.append(
                        DividendFact(
                            symbol=symbol,
                            report_date=actual_report_date,
                            indicator=indicator,
                            value_numeric=numeric,
                            value_text=text,
                            currency="CNY",
                            unit=unit,
                            raw={"ctr_name": CHOICE_DIVIDEND_CTR, "row": raw_row},
                        )
                    )
        return records

    def close(self) -> None:
        try:
            self.c.stop()
        except Exception:
            pass
