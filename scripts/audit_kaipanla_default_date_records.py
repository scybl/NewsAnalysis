#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stock_pipeline.kaipanla import DEFAULT_DATE, KAIPANLA_COLLECTION, DEFAULT_DB, _kaipanla_collection
from stock_pipeline.utils import timestamp


DATE_KEYS = ("date", "end_date", "trade_date")


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit/archive Kaipanla records that still use the default sample date.")
    parser.add_argument("--from-date", default="", help="Only scan records saved on or after YYYYMMDD / YYYY-MM-DD.")
    parser.add_argument("--to-date", default="", help="Only scan records saved on or before YYYYMMDD / YYYY-MM-DD.")
    parser.add_argument("--default-date", default=DEFAULT_DATE)
    parser.add_argument("--apply", action="store_true", help="Archive matching records. Default is dry-run.")
    parser.add_argument("--delete", action="store_true", help="Delete matching records instead of archiving them.")
    parser.add_argument("--include-archived", action="store_true", help="Also scan records already archived by a previous cleanup.")
    parser.add_argument("--limit-samples", type=int, default=20)
    args = parser.parse_args()

    default_compact = _compact_date(args.default_date)
    lower = _compact_date(args.from_date)
    upper = _compact_date(args.to_date)
    report = audit_default_date_records(
        default_compact=default_compact,
        lower=lower,
        upper=upper,
        apply=args.apply,
        delete=args.delete,
        include_archived=args.include_archived,
        sample_limit=max(1, args.limit_samples),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


def audit_default_date_records(
    *,
    default_compact: str,
    lower: str,
    upper: str,
    apply: bool,
    delete: bool,
    include_archived: bool,
    sample_limit: int,
) -> dict[str, Any]:
    scanned = 0
    matched_ids: list[str] = []
    samples: list[dict[str, Any]] = []
    by_feature: Counter[str] = Counter()
    query: dict[str, Any] = {} if include_archived else {"archived": {"$ne": True}}
    with _kaipanla_collection() as collection:
        cursor = collection.find(
            query,
            {
                "_id": 0,
                "record_id": 1,
                "feature": 1,
                "saved_at": 1,
                "run_id": 1,
                "params": 1,
                "path": 1,
            },
        ).sort([("saved_at", 1), ("feature", 1)])
        for record in cursor:
            scanned += 1
            saved_date = _compact_date(str(record.get("saved_at") or "")[:8])
            if lower and saved_date < lower:
                continue
            if upper and saved_date > upper:
                continue
            if saved_date == default_compact:
                continue
            params = record.get("params") if isinstance(record.get("params"), dict) else {}
            default_fields = [key for key in DATE_KEYS if _compact_date(params.get(key)) == default_compact]
            if not default_fields:
                continue
            record_id = str(record.get("record_id") or "")
            if not record_id:
                continue
            matched_ids.append(record_id)
            by_feature[str(record.get("feature") or "")] += 1
            if len(samples) < sample_limit:
                samples.append(
                    {
                        "record_id": record_id,
                        "feature": record.get("feature") or "",
                        "saved_at": record.get("saved_at") or "",
                        "run_id": record.get("run_id") or "",
                        "default_fields": default_fields,
                        "params": params,
                    }
                )
        modified = 0
        deleted = 0
        if (apply or delete) and matched_ids:
            if delete:
                result = collection.delete_many({"record_id": {"$in": matched_ids}})
                deleted = int(result.deleted_count)
            else:
                result = collection.update_many(
                    {"record_id": {"$in": matched_ids}},
                    {
                        "$set": {
                            "archived": True,
                            "archive_reason": f"default_sample_date_{default_compact}_does_not_match_saved_date",
                            "archived_at": timestamp(),
                        }
                    },
                )
                modified = int(result.modified_count)
    return {
        "ok": True,
        "database": DEFAULT_DB,
        "collection": KAIPANLA_COLLECTION,
        "mode": "delete" if delete else ("apply" if apply else "dry_run"),
        "default_date": _display_date(default_compact),
        "include_archived": include_archived,
        "scanned": scanned,
        "matched": len(matched_ids),
        "modified": modified,
        "deleted": deleted,
        "by_feature": dict(sorted(by_feature.items())),
        "samples": samples,
    }


def _compact_date(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[:8] if len(digits) >= 8 else ""


def _display_date(compact: str) -> str:
    return f"{compact[:4]}-{compact[4:6]}-{compact[6:8]}" if len(compact) == 8 else compact


if __name__ == "__main__":
    main()
