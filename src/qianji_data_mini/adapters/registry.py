"""Lazy adapter registry so unavailable proprietary SDKs do not break imports."""

from __future__ import annotations

from qianji_data_mini.adapters.base import DailyBarAdapter


def create_adapter(source: str) -> DailyBarAdapter:
    normalized = source.lower().strip()
    if normalized == "mock":
        from qianji_data_mini.adapters.mock import MockAdapter
        return MockAdapter()
    if normalized == "tushare":
        from qianji_data_mini.adapters.tushare import TushareAdapter
        return TushareAdapter()
    if normalized == "wind":
        from qianji_data_mini.adapters.wind import WindAdapter
        return WindAdapter()
    if normalized == "choice":
        from qianji_data_mini.adapters.choice import ChoiceAdapter
        return ChoiceAdapter()
    if normalized == "ifind":
        from qianji_data_mini.adapters.ifind import IFindAdapter
        return IFindAdapter()
    raise ValueError(f"不支持的数据源：{source}")

