"""Environment-based configuration with safe local defaults."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def env_float(name: str, default: float = 1.0) -> float:
    value = os.getenv(name)
    return float(value) if value not in (None, "") else default


def db_path() -> Path:
    configured = Path(os.getenv("QIANJI_DB_PATH", "./data/qianji_market.db"))
    if configured.is_absolute():
        return configured
    return (PROJECT_ROOT / configured).resolve()


def source_priority() -> list[str]:
    raw = os.getenv(
        "QIANJI_SOURCE_PRIORITY", "wind,choice,ifind,tushare,mock"
    )
    return [item.strip().lower() for item in raw.split(",") if item.strip()]

