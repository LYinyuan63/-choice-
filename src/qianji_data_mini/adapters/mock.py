"""Deterministic mock data for end-to-end testing without vendor accounts."""

from __future__ import annotations

import hashlib
import random
from datetime import date, timedelta

from qianji_data_mini.adapters.base import DailyBarAdapter
from qianji_data_mini.models import DailyBar


class MockAdapter(DailyBarAdapter):
    source = "mock"

    def fetch_daily(self, symbol: str, start_date: date, end_date: date) -> list[DailyBar]:
        seed = int(hashlib.sha256(symbol.encode("utf-8")).hexdigest()[:8], 16)
        rng = random.Random(seed)
        previous = 10 + rng.random() * 20
        current = start_date
        rows: list[DailyBar] = []
        while current <= end_date:
            if current.weekday() < 5:
                move = rng.uniform(-0.025, 0.025)
                open_price = previous * (1 + rng.uniform(-0.008, 0.008))
                close_price = previous * (1 + move)
                high = max(open_price, close_price) * (1 + rng.uniform(0, 0.012))
                low = min(open_price, close_price) * (1 - rng.uniform(0, 0.012))
                volume = float(rng.randint(1_000_000, 9_000_000))
                amount = volume * (open_price + close_price) / 2
                rows.append(
                    DailyBar(
                        symbol=symbol.upper(),
                        date=current,
                        open=round(open_price, 4),
                        high=round(high, 4),
                        low=round(low, 4),
                        close=round(close_price, 4),
                        volume=volume,
                        amount=round(amount, 2),
                        previous_close=round(previous, 4),
                        change_percent=round(move * 100, 4),
                        source=self.source,
                        raw={"generated": True},
                    )
                )
                previous = close_price
            current += timedelta(days=1)
        return rows

