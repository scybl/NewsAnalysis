#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stock_pipeline.kaipanla import KAIPANLA_FEATURES, run_kaipanla_batch
from stock_pipeline.utils import timestamp


SKIP_FEATURES = {
    "realtime_market_mood",
    "realtime_actual_limit_up_down",
    "realtime_board_stocks",
    "realtime_all_boards_stocks",
    "board_stocks_count_and_list",
    "realtime_index_trend",
    "realtime_index_list",
    "realtime_sharp_withdrawal",
    "realtime_rise_fall_analysis",
    "plate_news",
    "plate_news_dataframe",
    "ths_hot_rank",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill date-aware Kaipanla features for a date range.")
    parser.add_argument("--start-date", required=True, help="YYYY-MM-DD or YYYYMMDD")
    parser.add_argument("--end-date", required=True, help="YYYY-MM-DD or YYYYMMDD")
    parser.add_argument("--features", default="", help="Comma separated feature keys. Default: all date-aware features.")
    parser.add_argument("--include-weekends", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    start = _parse_date(args.start_date)
    end = _parse_date(args.end_date)
    if start > end:
        start, end = end, start
    features = _selected_features(args.features)
    dates = _date_range(start, end, include_weekends=args.include_weekends)
    report = {
        "ok": True,
        "mode": "dry_run" if args.dry_run else "apply",
        "date_range": {"start": start.isoformat(), "end": end.isoformat(), "dates": len(dates)},
        "features": features,
        "feature_count": len(features),
        "runs": [],
    }
    for current in dates:
        trade_date = current.isoformat()
        params = {key: _params_for_feature(key, trade_date) for key in features}
        if args.dry_run:
            result = {"ok": True, "trade_date": trade_date, "total": len(features), "succeeded": 0, "failed": 0, "dry_run": True}
        else:
            result = run_kaipanla_batch(
                features,
                params,
                save=True,
                run_id=f"{timestamp()}_backfill_{current.strftime('%Y%m%d')}",
                trade_date=trade_date,
            )
            if args.sleep > 0:
                time.sleep(args.sleep)
        report["runs"].append(
            {
                "trade_date": trade_date,
                "ok": bool(result.get("ok")),
                "succeeded": int(result.get("succeeded") or 0),
                "failed": int(result.get("failed") or 0),
                "total": int(result.get("total") or len(features)),
                "failed_features": [item.get("feature") for item in result.get("results", []) if not item.get("ok")],
            }
        )
        print(json.dumps(report["runs"][-1], ensure_ascii=False), flush=True)
    report["summary"] = {
        "dates": len(report["runs"]),
        "successful_dates": sum(1 for item in report["runs"] if item["ok"]),
        "failed_dates": sum(1 for item in report["runs"] if not item["ok"]),
        "feature_runs": sum(item["total"] for item in report["runs"]),
        "failed_feature_runs": sum(item["failed"] for item in report["runs"]),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


def _selected_features(raw: str) -> list[str]:
    if raw.strip():
        selected = [item.strip() for item in raw.split(",") if item.strip()]
    else:
        selected = [
            key
            for key, feature in KAIPANLA_FEATURES.items()
            if key not in SKIP_FEATURES
            and any(param in feature.default_params for param in ("date", "end_date", "trade_date"))
        ]
    unknown = [key for key in selected if key not in KAIPANLA_FEATURES]
    if unknown:
        raise SystemExit(f"Unknown Kaipanla features: {', '.join(unknown)}")
    return selected


def _params_for_feature(feature_key: str, trade_date: str) -> dict[str, Any]:
    params = dict(KAIPANLA_FEATURES[feature_key].default_params)
    if "date" in params:
        params["date"] = trade_date
    if "end_date" in params:
        params["end_date"] = trade_date
    if "trade_date" in params:
        params["trade_date"] = trade_date
    if "start_date" in params and "end_date" in params:
        params["start_date"] = trade_date
    return params


def _date_range(start: date, end: date, *, include_weekends: bool) -> list[date]:
    days = []
    current = start
    while current <= end:
        if include_weekends or current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def _parse_date(value: str) -> date:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) != 8:
        raise SystemExit(f"Invalid date: {value}")
    return datetime.strptime(digits, "%Y%m%d").date()


if __name__ == "__main__":
    main()
