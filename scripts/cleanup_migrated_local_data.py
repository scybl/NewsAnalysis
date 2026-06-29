from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from stock_pipeline.config import PROJECT_ROOT
from stock_pipeline.local_data_mongo import list_mongo_stock_codes


LOCAL_DATA_DIR = PROJECT_ROOT / "local_data"
KAIPANLA_DATA_DIR = LOCAL_DATA_DIR / "kaipanla"
STOCK_DIR_RE = re.compile(r"^\d{6}\.(SZ|SH|BJ)$")
TEMP_STOCK_DIR_RE = re.compile(r"^\.\d{6}\.(SZ|SH|BJ)\.tmp_\d{8}_\d{6}$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Delete migrated local business data after MongoDB verification.")
    parser.add_argument("--apply", action="store_true", help="Actually delete files. Without this, only report planned deletes.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    mongo_codes = set(list_mongo_stock_codes())
    planned: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    if not LOCAL_DATA_DIR.exists():
        print(json.dumps({"ok": True, "planned": [], "skipped": [], "applied": args.apply}, ensure_ascii=False, indent=2))
        return 0

    for path in sorted(LOCAL_DATA_DIR.iterdir()):
        if not path.is_dir():
            continue
        if STOCK_DIR_RE.fullmatch(path.name):
            if path.name in mongo_codes:
                planned.append({"path": str(path), "kind": "stock_package_dir"})
            else:
                skipped.append({"path": str(path), "reason": "stock code not found in MongoDB"})
        elif TEMP_STOCK_DIR_RE.fullmatch(path.name):
            planned.append({"path": str(path), "kind": "stale_stock_temp_dir"})

    if KAIPANLA_DATA_DIR.exists():
        planned.append({"path": str(KAIPANLA_DATA_DIR), "kind": "legacy_kaipanla_dir"})

    if args.apply:
        for item in planned:
            shutil.rmtree(item["path"], ignore_errors=False)

    print(
        json.dumps(
            {
                "ok": not skipped,
                "applied": args.apply,
                "mongo_stock_codes": len(mongo_codes),
                "planned_count": len(planned),
                "planned": planned[:200],
                "skipped": skipped,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not skipped else 1


if __name__ == "__main__":
    raise SystemExit(main())
