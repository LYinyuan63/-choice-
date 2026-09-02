"""Beginner-friendly command line entry point."""

from __future__ import annotations

import argparse
from pathlib import Path

from qianji_data_mini.db import Database
from qianji_data_mini.financial_ingest import ingest_choice_financial_sample
from qianji_data_mini.ingest import ingest_daily


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qianji-data")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="创建 SQLite 表")
    sub.add_parser("status", help="查看各数据源记录数")

    ingest_parser = sub.add_parser("ingest", help="下载并写入日线")
    ingest_parser.add_argument("--source", required=True, choices=["mock", "tushare", "wind", "choice", "ifind"])
    ingest_parser.add_argument("--symbols", required=True, help="逗号分隔代码")
    ingest_parser.add_argument("--start", required=True)
    ingest_parser.add_argument("--end", required=True)

    financial_parser = sub.add_parser(
        "ingest-choice-financial",
        help="通过Choice官方CTR下载财务报表与分红并落库",
    )
    financial_parser.add_argument("--symbols", required=True, help="逗号分隔代码")
    financial_parser.add_argument(
        "--report-dates", required=True, help="逗号分隔报告期，格式YYYY-MM-DD"
    )
    financial_parser.add_argument(
        "--report-type", type=int, choices=[1, 2, 3, 4],
        help="默认读取CHOICE_CTR_REPORT_TYPE，未配置时为1",
    )

    query_parser = sub.add_parser("query", help="查询日线")
    query_parser.add_argument("--symbol", required=True)
    query_parser.add_argument("--source", default="auto")
    query_parser.add_argument("--start")
    query_parser.add_argument("--end")

    export_parser = sub.add_parser("export-excel", help="导出 Excel")
    export_parser.add_argument("--symbol", required=True)
    export_parser.add_argument("--source", default="auto")
    export_parser.add_argument("--start")
    export_parser.add_argument("--end")
    export_parser.add_argument("--output", default="qianji_market_data.xlsx")

    sub.add_parser("serve", help="启动本地 REST 服务")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    database = Database()
    if args.command == "init-db":
        print(f"数据库已创建：{database.path}")
    elif args.command == "status":
        print(database.source_status().to_string(index=False))
    elif args.command == "ingest":
        result = ingest_daily(
            source=args.source, symbols=args.symbols,
            start_date=args.start, end_date=args.end,
            database_path=database.path,
        )
        print(result.model_dump_json(indent=2))
    elif args.command == "ingest-choice-financial":
        result = ingest_choice_financial_sample(
            symbols=args.symbols.split(","),
            report_dates=args.report_dates.split(","),
            report_type=args.report_type,
            database_path=database.path,
        )
        print(result.model_dump_json(indent=2))
    elif args.command == "query":
        frame = database.query_dataframe(
            symbol=args.symbol, source=args.source,
            start_date=args.start, end_date=args.end,
        )
        print(frame.to_string(index=False))
    elif args.command == "export-excel":
        frame = database.query_dataframe(
            symbol=args.symbol, source=args.source,
            start_date=args.start, end_date=args.end,
        )
        output = Path(args.output).resolve()
        frame.to_excel(output, index=False)
        print(f"已导出：{output}")
    elif args.command == "serve":
        from qianji_data_mini.service import run
        run()


if __name__ == "__main__":
    main()
