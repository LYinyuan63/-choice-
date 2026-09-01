"""Common adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from qianji_data_mini.models import DailyBar


class AdapterError(RuntimeError):
    """A vendor SDK, permission or response-format error."""


class DailyBarAdapter(ABC):
    source: str

    @abstractmethod
    def fetch_daily(self, symbol: str, start_date: date, end_date: date) -> list[DailyBar]:
        raise NotImplementedError

    def close(self) -> None:
        return None

