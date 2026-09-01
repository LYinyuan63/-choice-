"""Validation helpers shared by Choice fetchers."""

from __future__ import annotations

from datetime import date, datetime


SUPPORTED_SUFFIXES = {"SH", "SZ", "BJ", "HK"}


def normalize_choice_symbol(value: str) -> str:
    """Normalize a single symbol while rejecting ambiguous foreign markets."""
    symbol = value.strip().upper().replace(".SS", ".SH")
    if not symbol:
        raise ValueError("Choice symbol cannot be empty.")
    if symbol.isdigit() and len(symbol) in {5, 6}:
        if len(symbol) == 5:
            return f"{symbol}.HK"
        suffix = "SH" if symbol[0] in {"5", "6", "9"} else "SZ"
        return f"{symbol}.{suffix}"
    if "." not in symbol:
        raise ValueError(
            f"Invalid Choice symbol '{value}'. Use a code such as 000001.SZ."
        )
    code, suffix = symbol.rsplit(".", 1)
    if not code or suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(
            f"Unsupported Choice market in '{value}'. P0 supports SH, SZ, BJ and HK."
        )
    return f"{code}.{suffix}"


def normalize_choice_symbol_list(value: str) -> str:
    """Normalize and deduplicate a comma-separated symbol list."""
    symbols = [normalize_choice_symbol(item) for item in value.split(",") if item.strip()]
    if not symbols:
        raise ValueError("At least one Choice symbol is required.")
    return ",".join(dict.fromkeys(symbols))


def validate_iso_date(value: object, field_name: str) -> object:
    """Reject non-ISO string dates before Pydantic coerces them."""
    if value is None or isinstance(value, (date, datetime)):
        return value
    if isinstance(value, str):
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(
                f"Invalid '{field_name}' format. Expected YYYY-MM-DD."
            ) from exc
    return value
