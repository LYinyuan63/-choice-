"""Minimal, credential-safe wrapper around the official Choice EmQuantAPI SDK."""

from __future__ import annotations

import os
import re
import warnings
from datetime import date, datetime
from math import isnan
from typing import Any, Literal


class ChoiceSDKError(RuntimeError):
    """Base class for handled Choice SDK failures."""


class ChoiceAuthenticationError(ChoiceSDKError):
    """Choice login or authorization failed."""


class ChoiceEmptyRecordWarning(UserWarning):
    """A Choice period placeholder contained no usable OHLC values."""


def _credential(
    credentials: dict[str, str] | None,
    credential_name: str,
    environment_name: str,
) -> str:
    value = (credentials or {}).get(credential_name, "")
    return str(value or os.getenv(environment_name, ""))


def build_login_options(credentials: dict[str, str] | None = None) -> str:
    """Build c.start options without printing or persisting credentials."""
    username = _credential(credentials, "choice_username", "CHOICE_USERNAME").strip()
    password = _credential(credentials, "choice_password", "CHOICE_PASSWORD")
    mode = os.getenv("CHOICE_LOGIN_MODE", "auto").strip().lower()
    base = os.getenv(
        "CHOICE_START_OPTIONS",
        "ForceLogin=0,TestLatency=0,RecordLoginInfo=0",
    ).strip()

    if mode not in {"auto", "password", "userinfo"}:
        raise ChoiceAuthenticationError(
            "CHOICE_LOGIN_MODE must be auto, password, or userinfo."
        )
    if "forcelogin=1" in base.replace(" ", "").lower() and os.getenv(
        "CHOICE_ALLOW_FORCE_LOGIN"
    ) != "1":
        raise ChoiceAuthenticationError(
            "ForceLogin=1 is blocked by default because it can terminate another session."
        )
    if mode == "auto":
        mode = "password" if username or password else "userinfo"
    if mode == "userinfo":
        return base
    if not username or not password:
        raise ChoiceAuthenticationError(
            "Choice password login requires choice_username and choice_password."
        )
    if any(char in username + password for char in [",", "\n", "\r"]):
        raise ChoiceAuthenticationError(
            "Choice credentials contain a comma or newline; use LoginActivator/userInfo instead."
        )
    return f"UserName={username},PassWord={password},{base}"


def _number(value: Any) -> float | None:
    if value in (None, "", "--", "None"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if isnan(number) else number


def _iso_date(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()

    # Choice can return dates such as ``2026/7/17`` as well as ISO dates.
    # Parse the calendar components explicitly so zero-padding and separators
    # do not affect the standardized OpenBB result.
    separated = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
    if separated:
        year, month, day = (int(item) for item in separated.groups())
        try:
            return date(year, month, day).isoformat()
        except ValueError as exc:
            raise ChoiceSDKError(f"Invalid Choice response date: {value!r}.") from exc

    compact = re.match(r"^(\d{4})(\d{2})(\d{2})$", text)
    if compact:
        year, month, day = (int(item) for item in compact.groups())
        try:
            return date(year, month, day).isoformat()
        except ValueError as exc:
            raise ChoiceSDKError(f"Invalid Choice response date: {value!r}.") from exc

    raise ChoiceSDKError(f"Unsupported Choice response date format: {value!r}.")


def _indicator_series(response: Any, symbol: str) -> tuple[list[str], dict[str, list[Any]]]:
    dates = list(getattr(response, "Dates", []) or [])
    indicators = [
        str(item).upper()
        for item in (getattr(response, "Indicators", []) or [])
    ]
    payload = getattr(response, "Data", {})
    if isinstance(payload, dict):
        values = payload.get(symbol)
        if values is None:
            values = payload.get(symbol.upper())
    else:
        values = payload
    if values is None:
        raise ChoiceSDKError(f"Choice response has no data for {symbol}.")

    if isinstance(values, dict):
        series = {
            str(name).upper(): list(items)
            for name, items in values.items()
        }
    elif values and isinstance(values[0], (list, tuple)):
        if len(values) != len(indicators):
            raise ChoiceSDKError(
                f"Choice response shape does not match Indicators for {symbol}."
            )
        series = {
            name: list(values[index])
            for index, name in enumerate(indicators)
        }
    elif len(values) == len(indicators) * len(dates):
        series = {
            name: list(values[index * len(dates):(index + 1) * len(dates)])
            for index, name in enumerate(indicators)
        }
    else:
        raise ChoiceSDKError(
            f"Unsupported Choice response shape for {symbol}; "
            "record only Codes, Dates length, Indicators and Data type when reporting it."
        )
    if any(len(items) != len(dates) for items in series.values()):
        raise ChoiceSDKError(f"Choice series length mismatch for {symbol}.")
    return dates, series


class ChoiceClient:
    """One short-lived EmQuantAPI login session used by an OpenBB fetcher."""

    indicators = (
        "OPEN", "HIGH", "LOW", "CLOSE", "VOLUME", "AMOUNT", "PRECLOSE", "PCTCHANGE"
    )

    def __init__(self, credentials: dict[str, str] | None = None):
        self.credentials = credentials
        self.api: Any = None

    def __enter__(self) -> "ChoiceClient":
        try:
            from EmQuantAPI import c
        except ImportError as exc:
            raise ChoiceSDKError(
                "EmQuantAPI is not installed in this Python environment. "
                "Install the official Choice Python SDK before using provider='choice'."
            ) from exc
        self.api = c
        result = self.api.start(build_login_options(self.credentials))
        error_code = getattr(result, "ErrorCode", result if isinstance(result, int) else -1)
        if error_code != 0:
            error_message = getattr(result, "ErrorMsg", "No error message returned")
            raise ChoiceAuthenticationError(
                f"Choice login failed (ErrorCode={error_code}): {error_message}"
            )
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self.api is not None:
            try:
                self.api.stop()
            except Exception:
                pass

    def historical(
        self,
        *,
        symbols: list[str],
        start_date: date,
        end_date: date,
        period: Literal["daily", "weekly", "monthly"] = "daily",
        adjustment: Literal["qfq", "hfq"] | None = None,
    ) -> list[dict[str, Any]]:
        """Download historical OHLCV, one symbol per SDK request."""
        period_code = {"daily": 1, "weekly": 2, "monthly": 3}[period]
        adjustment_code = {None: 1, "hfq": 2, "qfq": 3}[adjustment]
        options = (
            f"Period={period_code},AdjustFlag={adjustment_code},"
            "CurType=1,Order=1"
        )
        volume_multiplier = float(os.getenv("CHOICE_VOLUME_MULTIPLIER", "1") or 1)
        amount_multiplier = float(os.getenv("CHOICE_AMOUNT_MULTIPLIER", "1") or 1)
        records: list[dict[str, Any]] = []

        for requested_symbol in symbols:
            symbol = requested_symbol.upper()
            response = self.api.csd(
                symbol,
                ",".join(self.indicators),
                start_date.isoformat(),
                end_date.isoformat(),
                options,
            )
            error_code = getattr(response, "ErrorCode", -1)
            if error_code != 0:
                error_message = getattr(response, "ErrorMsg", "No error message returned")
                raise ChoiceSDKError(
                    f"Choice csd failed for {symbol} "
                    f"(ErrorCode={error_code}): {error_message}"
                )
            dates, series = _indicator_series(response, symbol)
            for index, value_date in enumerate(dates):
                raw = {
                    name: values[index]
                    for name, values in series.items()
                }
                standard_date = _iso_date(value_date)
                ohlc = {
                    "open": _number(raw.get("OPEN")),
                    "high": _number(raw.get("HIGH")),
                    "low": _number(raw.get("LOW")),
                    "close": _number(raw.get("CLOSE")),
                }
                missing_ohlc = [name for name, value in ohlc.items() if value is None]

                # Choice can return an unfinished weekly/monthly period as a dated
                # placeholder whose OHLC values are all empty.  It is not a market
                # bar and must not be passed into OpenBB's required OHLC model.
                if len(missing_ohlc) == len(ohlc):
                    warnings.warn(
                        "Choice skipped all-empty OHLC placeholder "
                        f"(symbol={symbol}, date={standard_date}, period={period}).",
                        ChoiceEmptyRecordWarning,
                        stacklevel=2,
                    )
                    continue

                # A partly populated OHLC row is different from a harmless empty
                # placeholder: fail explicitly so real source-data damage is visible.
                if missing_ohlc:
                    missing_text = ",".join(item.upper() for item in missing_ohlc)
                    raise ChoiceSDKError(
                        "Choice returned incomplete OHLC "
                        f"(symbol={symbol}, date={standard_date}, period={period}, "
                        f"missing={missing_text})."
                    )

                close = ohlc["close"]
                prev_close = _number(raw.get("PRECLOSE"))
                pct_change_points = _number(raw.get("PCTCHANGE"))
                volume = _number(raw.get("VOLUME"))
                amount = _number(raw.get("AMOUNT"))
                records.append(
                    {
                        "symbol": symbol,
                        "date": standard_date,
                        "open": ohlc["open"],
                        "high": ohlc["high"],
                        "low": ohlc["low"],
                        "close": close,
                        "volume": volume * volume_multiplier if volume is not None else None,
                        "amount": amount * amount_multiplier if amount is not None else None,
                        "prev_close": prev_close,
                        "change": (
                            close - prev_close
                            if close is not None and prev_close is not None
                            else None
                        ),
                        "change_percent": (
                            pct_change_points / 100
                            if pct_change_points is not None
                            else None
                        ),
                        "source": "choice",
                        "volume_unit": "share",
                        "amount_unit": "CNY",
                        "timezone": "Asia/Shanghai",
                    }
                )
        return records
