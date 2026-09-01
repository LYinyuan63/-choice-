"""Small, credential-safe real-source validation run and evidence export."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd

from qianji_data_mini.config import db_path as configured_db_path
from qianji_data_mini.db import Database
from qianji_data_mini.ingest import ingest_daily


@dataclass
class SourceResult:
    source: str
    status: str
    received_rows: int = 0
    stored_rows: int = 0
    symbols_with_data: int = 0
    start_date: str | None = None
    end_date: str | None = None
    message: str = ""


def default_date_range() -> tuple[date, date]:
    end = date.today()
    return end - timedelta(days=35), end


def _safe_message(value: object) -> str:
    message = str(value)
    for name in ("TUSHARE_TOKEN", "CHOICE_USERNAME", "CHOICE_PASSWORD"):
        secret = os.getenv(name, "")
        if secret:
            message = message.replace(secret, "***")
    return message


def _frame_for_source(
    database: Database,
    source: str,
    symbols: Iterable[str],
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    frames = [
        database.query_dataframe(
            symbol=symbol,
            source=source,
            start_date=start_date,
            end_date=end_date,
        )
        for symbol in symbols
    ]
    frames = [frame for frame in frames if not frame.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _quality_checks(source: str, frame: pd.DataFrame) -> list[dict]:
    checks: list[dict] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append(
            {
                "source": source,
                "check": name,
                "result": "PASS" if passed else "FAIL",
                "detail": detail,
            }
        )

    if frame.empty:
        add("返回非空", False, "没有取得任何日线记录")
        return checks

    key_columns = ["source", "symbol", "date"]
    missing_keys = int(frame[key_columns].isna().any(axis=1).sum())
    duplicates = int(frame.duplicated(key_columns).sum())
    add("返回非空", True, f"共 {len(frame)} 条")
    add("主键完整", missing_keys == 0, f"缺失主键 {missing_keys} 条")
    add("主键唯一", duplicates == 0, f"重复 {duplicates} 条")

    ohlc = frame[["open", "high", "low", "close"]].apply(
        pd.to_numeric, errors="coerce"
    )
    complete = ohlc.notna().all(axis=1)
    invalid_ohlc = int(
        (
            complete
            & (
                (ohlc["high"] < ohlc.max(axis=1))
                | (ohlc["low"] > ohlc.min(axis=1))
            )
        ).sum()
    )
    add("OHLC逻辑", invalid_ohlc == 0, f"异常 {invalid_ohlc} 条")

    volume = pd.to_numeric(frame["volume"], errors="coerce")
    negative_volume = int((volume.dropna() < 0).sum())
    add("成交量非负", negative_volume == 0, f"负数 {negative_volume} 条")

    unit_ok = set(frame["volume_unit"].dropna()) <= {"share"}
    amount_ok = set(frame["amount_unit"].dropna()) <= {"CNY"}
    add(
        "标准单位",
        unit_ok and amount_ok,
        "volume=share，amount=CNY" if unit_ok and amount_ok else "单位字段不符合公司口径",
    )
    return checks


def _cross_source_comparison(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    available = [(source, frame) for source, frame in frames.items() if not frame.empty]
    columns = [
        "symbol", "date", "source_left", "source_right",
        "close_left", "close_right", "close_abs_diff",
        "close_diff_pct", "volume_left", "volume_right", "volume_ratio",
    ]
    if len(available) < 2:
        return pd.DataFrame(columns=columns)

    rows = []
    for index, (left_name, left) in enumerate(available):
        for right_name, right in available[index + 1:]:
            merged = left[["symbol", "date", "close", "volume"]].merge(
                right[["symbol", "date", "close", "volume"]],
                on=["symbol", "date"],
                suffixes=("_left", "_right"),
            )
            for item in merged.to_dict(orient="records"):
                left_close = item.get("close_left")
                right_close = item.get("close_right")
                left_volume = item.get("volume_left")
                right_volume = item.get("volume_right")
                close_abs_diff = (
                    abs(left_close - right_close)
                    if left_close is not None and right_close is not None
                    else None
                )
                close_diff_pct = (
                    close_abs_diff / abs(left_close) * 100
                    if close_abs_diff is not None and left_close not in (None, 0)
                    else None
                )
                volume_ratio = (
                    right_volume / left_volume
                    if left_volume not in (None, 0) and right_volume is not None
                    else None
                )
                rows.append(
                    {
                        "symbol": item["symbol"],
                        "date": item["date"],
                        "source_left": left_name,
                        "source_right": right_name,
                        "close_left": left_close,
                        "close_right": right_close,
                        "close_abs_diff": close_abs_diff,
                        "close_diff_pct": close_diff_pct,
                        "volume_left": left_volume,
                        "volume_right": right_volume,
                        "volume_ratio": volume_ratio,
                    }
                )
    return pd.DataFrame(rows, columns=columns)


def run_validation(
    *,
    sources: list[str],
    symbols: list[str],
    start_date: date,
    end_date: date,
    database_path: str | Path | None = None,
    output_dir: str | Path = "validation_output",
) -> dict:
    """Fetch small real samples, store them, and produce non-secret evidence."""

    database = Database(database_path or configured_db_path())
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    clean_symbols = list(dict.fromkeys(item.strip().upper() for item in symbols if item.strip()))
    clean_sources = list(dict.fromkeys(item.strip().lower() for item in sources if item.strip()))

    summaries: list[SourceResult] = []
    quality: list[dict] = []
    frames: dict[str, pd.DataFrame] = {}

    for source in clean_sources:
        try:
            ingestion = ingest_daily(
                source=source,
                symbols=clean_symbols,
                start_date=start_date,
                end_date=end_date,
                database_path=database.path,
            )
            frame = _frame_for_source(
                database, source, clean_symbols, start_date, end_date
            )
            frames[source] = frame
            status = "PASS" if not frame.empty and not ingestion.failed_symbols else "PARTIAL"
            summaries.append(
                SourceResult(
                    source=source,
                    status=status,
                    received_rows=ingestion.received_rows,
                    stored_rows=ingestion.stored_rows,
                    symbols_with_data=(
                        int(frame["symbol"].nunique()) if not frame.empty else 0
                    ),
                    start_date=(str(frame["date"].min()) if not frame.empty else None),
                    end_date=(str(frame["date"].max()) if not frame.empty else None),
                    message=(
                        _safe_message(json.dumps(ingestion.failed_symbols, ensure_ascii=False))
                        if ingestion.failed_symbols
                        else (
                            "模拟调用及落库完成"
                            if source == "mock"
                            else "真实调用及落库完成"
                        )
                    ),
                )
            )
            quality.extend(_quality_checks(source, frame))
        except Exception as exc:
            frames[source] = pd.DataFrame()
            summaries.append(
                SourceResult(
                    source=source,
                    status="FAIL",
                    message=_safe_message(f"{type(exc).__name__}: {exc}"),
                )
            )
            quality.extend(_quality_checks(source, pd.DataFrame()))

    summary_frame = pd.DataFrame(asdict(item) for item in summaries)
    quality_frame = pd.DataFrame(quality)
    comparison_frame = _cross_source_comparison(frames)
    status_frame = database.source_status()
    data_map = pd.DataFrame(
        [
            {
                "priority": "P0",
                "dataset": "A股日线行情验证集",
                "symbols": ",".join(clean_symbols),
                "date_range": f"{start_date.isoformat()} 至 {end_date.isoformat()}",
                "sources": ",".join(clean_sources),
                "target_table": "daily_bar",
                "standard_key": "source+symbol+trade_date+adjustment",
                "volume_unit": "share",
                "amount_unit": "CNY",
                "openbb_route": "equity.price.historical / provider=qianji",
                "export": "Excel/SQLite",
            }
        ]
    )

    workbook = output / "真实数据验证证据.xlsx"
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        summary_frame.to_excel(writer, sheet_name="验证汇总", index=False)
        data_map.to_excel(writer, sheet_name="数据地图", index=False)
        quality_frame.to_excel(writer, sheet_name="质量检查", index=False)
        status_frame.to_excel(writer, sheet_name="数据库落库统计", index=False)
        comparison_frame.to_excel(writer, sheet_name="跨源对比", index=False)
        for source, frame in frames.items():
            if not frame.empty:
                frame.to_excel(writer, sheet_name=f"{source}_日线"[:31], index=False)

    evidence = {
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "database": str(database.path),
        "workbook": str(workbook),
        "sources": clean_sources,
        "symbols": clean_symbols,
        "date_range": [start_date.isoformat(), end_date.isoformat()],
        "results": [asdict(item) for item in summaries],
        "credentials_included": False,
    }
    json_path = output / "真实数据验证结果.json"
    json_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    evidence["json"] = str(json_path)
    return evidence
