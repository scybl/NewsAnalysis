#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stock_pipeline.stock_volume_price_metadata import (  # noqa: E402
    DEFAULT_DAILY_SUMMARY_MODE,
    DEFAULT_MINUTE_SOURCE,
    DEFAULT_MONGO_SOCKET_TIMEOUT_MS,
    DEFAULT_VOLUME_SAMPLE_DAYS,
    DEFAULT_VOLUME_TOLERANCE,
    export_stock_volume_price_metadata,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="导出全部股票量价数据 metadata 表。")
    parser.add_argument(
        "--output",
        "-o",
        default="reports/stock-volume-price-metadata.csv",
        help="输出路径；使用 - 输出到 stdout。默认 reports/stock-volume-price-metadata.csv",
    )
    parser.add_argument("--format", choices=["auto", "csv", "md", "markdown", "json"], default="auto", help="输出格式，默认按后缀推断。")
    parser.add_argument("--codes", default="", help="只导出指定股票，逗号分隔，例如 000001.SZ,600000.SH。")
    parser.add_argument("--limit", type=int, default=0, help="最多导出多少只股票，0 表示不限制。")
    parser.add_argument("--minute-source", default=DEFAULT_MINUTE_SOURCE, help=f"分时数据源，默认 {DEFAULT_MINUTE_SOURCE}。")
    parser.add_argument("--volume-sample-days", type=int, default=DEFAULT_VOLUME_SAMPLE_DAYS, help="成交量抽检最近热缓存分时天数，0 表示跳过。")
    parser.add_argument("--volume-tolerance", type=float, default=DEFAULT_VOLUME_TOLERANCE, help="成交量相对误差容忍度，默认 0.15。")
    parser.add_argument(
        "--daily-summary-mode",
        choices=["coverage", "aggregate"],
        default=DEFAULT_DAILY_SUMMARY_MODE,
        help="日K摘要来源；coverage 使用 stock_daily_coverage 快速导出，aggregate 强制扫描日K明细重算。",
    )
    parser.add_argument(
        "--mongo-socket-timeout-ms",
        type=int,
        default=DEFAULT_MONGO_SOCKET_TIMEOUT_MS,
        help="Mongo 单次读超时毫秒，默认 600000。",
    )
    parser.add_argument("--quiet", action="store_true", help="不在 stderr 打印进度。")
    args = parser.parse_args()

    codes = [item.strip() for item in args.codes.split(",") if item.strip()]
    progress = None if args.quiet else (lambda message: print(message, file=sys.stderr, flush=True))
    result = export_stock_volume_price_metadata(
        args.output,
        output_format=args.format,
        codes=codes,
        limit=args.limit or None,
        minute_source=args.minute_source,
        volume_sample_days=args.volume_sample_days,
        volume_tolerance=args.volume_tolerance,
        daily_summary_mode=args.daily_summary_mode,
        mongo_socket_timeout_ms=args.mongo_socket_timeout_ms,
        progress=progress,
    )
    print(json.dumps(result, ensure_ascii=False), file=sys.stderr)


if __name__ == "__main__":
    main()
