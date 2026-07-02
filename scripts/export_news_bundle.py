from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bson import json_util
from pymongo import ASCENDING, DESCENDING, MongoClient, ReplaceOne

REPO_ROOT = Path(__file__).resolve().parents[1]
NEWSCRAWLER_SRC = REPO_ROOT / "NewsCrawler" / "src"
if str(NEWSCRAWLER_SRC) not in sys.path:
    sys.path.insert(0, str(NEWSCRAWLER_SRC))

from news_crawler.config import get_settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export/import portable NewsCrawler article bundles.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    export = subparsers.add_parser("export", help="Export article documents into a portable bundle.")
    export.add_argument("--source", default="guardian")
    export.add_argument("--limit", type=int, default=8000)
    export.add_argument("--order", choices=("oldest", "newest"), default="oldest")
    export.add_argument("--output-dir", default="")
    export.add_argument("--database", default="")
    export.add_argument("--collection", default="")
    export.add_argument("--archive", action="store_true", help="Also create a .tar.gz archive. Object directory is always created.")

    import_cmd = subparsers.add_parser("import", help="Import a portable article bundle.")
    import_cmd.add_argument("bundle", help="Bundle directory or .tar.gz file.")
    import_cmd.add_argument("--database", default="")
    import_cmd.add_argument("--collection", default="")
    import_cmd.add_argument("--batch-size", type=int, default=1000)
    import_cmd.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "export":
        result = export_bundle(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    result = import_bundle(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def export_bundle(args: argparse.Namespace) -> dict[str, str]:
    settings = get_settings()
    database = args.database or settings.mongodb_database
    collection = args.collection or settings.raw_collection
    limit = max(1, int(args.limit or 8000))
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_root = Path(args.output_dir or (Path.cwd() / "exports"))
    bundle_dir = output_root / f"{args.source}_articles_{args.order}_{limit}_{now}"
    bundle_dir.mkdir(parents=True, exist_ok=False)

    objects_dir = bundle_dir / "objects" / args.source
    indexes_dir = bundle_dir / "indexes"
    indexes_dir.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    sort_direction = ASCENDING if args.order == "oldest" else DESCENDING
    query = {"source_name": args.source}
    projection = {"_id": 0}
    total = 0
    checksum = hashlib.sha256()
    first_published = ""
    last_published = ""
    index_path = indexes_dir / "articles.jsonl"

    with MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=8000) as client:
        cursor = (
            client[database][collection]
            .find(query, projection)
            .sort("published_at", sort_direction)
            .limit(limit)
        )
        with index_path.open("w", encoding="utf-8") as index_fh:
            for doc in cursor:
                published = str(doc.get("published_at") or "")
                first_published = first_published or published
                last_published = published or last_published
                key = stable_article_key(doc)
                object_path = article_object_path(objects_dir, published, key)
                object_path.parent.mkdir(parents=True, exist_ok=True)
                body = json_util.dumps(doc, ensure_ascii=False, indent=2)
                object_path.write_text(body + "\n", encoding="utf-8")
                rel_path = relative_path(object_path, bundle_dir)
                entry = {
                    "source_name": doc.get("source_name") or args.source,
                    "article_id": doc.get("article_id") or "",
                    "source_external_key": doc.get("source_external_key") or "",
                    "canonical_url": doc.get("canonical_url") or "",
                    "url": doc.get("url") or "",
                    "title": doc.get("title") or "",
                    "published_at": published,
                    "path": rel_path,
                    "sha256": hashlib.sha256((body + "\n").encode("utf-8")).hexdigest(),
                }
                line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
                index_fh.write(line + "\n")
                checksum.update((line + "\n").encode("utf-8"))
                total += 1

    manifest = {
        "bundle_format": "newsanalysis.news_articles.object.v1",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_name": args.source,
        "database": database,
        "collection": collection,
        "order": args.order,
        "limit": limit,
        "count": total,
        "first_published_at": first_published,
        "last_published_at": last_published,
        "objects_root": relative_path(objects_dir, bundle_dir),
        "index_file": relative_path(index_path, bundle_dir),
        "sha256_index": checksum.hexdigest(),
    }
    write_json(bundle_dir / "manifest.json", manifest)
    write_text(bundle_dir / "import.sh", import_script())
    write_text(bundle_dir / "export_guardian_8000.sh", export_script())
    os.chmod(bundle_dir / "import.sh", 0o755)
    os.chmod(bundle_dir / "export_guardian_8000.sh", 0o755)
    write_text(bundle_dir / "README.md", readme_text(manifest))

    result = {"bundle_dir": str(bundle_dir)}
    if args.archive:
        archive_path = shutil.make_archive(str(bundle_dir), "gztar", root_dir=output_root, base_dir=bundle_dir.name)
        result["archive"] = str(archive_path)
    return result


def import_bundle(args: argparse.Namespace) -> dict[str, Any]:
    settings = get_settings()
    bundle_dir = unpack_if_needed(Path(args.bundle))
    manifest = read_json(bundle_dir / "manifest.json")
    index_path = bundle_dir / str(manifest.get("index_file") or "indexes/articles.jsonl")
    database = args.database or manifest.get("database") or settings.mongodb_database
    collection_name = args.collection or manifest.get("collection") or settings.raw_collection
    batch_size = max(1, int(args.batch_size or 1000))

    operations: list[Any] = []
    total = 0
    with MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=8000) as client:
        collection = client[str(database)][str(collection_name)]
        ensure_article_indexes(collection)
        with index_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                entry = json.loads(line)
                doc_path = bundle_dir / str(entry.get("path") or "")
                if not doc_path.exists():
                    continue
                doc = json_util.loads(doc_path.read_text(encoding="utf-8"))
                key = article_key(doc)
                if not key:
                    continue
                operations.append(ReplaceOne(key, doc, upsert=True))
                total += 1
                if len(operations) >= batch_size:
                    if not args.dry_run:
                        collection.bulk_write(operations, ordered=False)
                    operations = []
        if operations and not args.dry_run:
            collection.bulk_write(operations, ordered=False)
    return {"bundle": str(bundle_dir), "dry_run": bool(args.dry_run), "documents": total}


def ensure_article_indexes(collection: Any) -> None:
    collection.create_index([("article_id", ASCENDING)], unique=True, name="uk_raw_article_id")
    collection.create_index([("source_external_key", ASCENDING)], unique=True, sparse=True, name="uk_raw_source_external")
    collection.create_index([("canonical_url", ASCENDING)], unique=True, sparse=True, name="uk_raw_canonical_url")
    collection.create_index([("source_name", ASCENDING), ("published_at", DESCENDING)], name="idx_raw_source_published")
    collection.create_index([("published_at", DESCENDING)], name="idx_raw_published")


def article_key(doc: dict[str, Any]) -> dict[str, Any]:
    for field in ("article_id", "source_external_key", "canonical_url", "url"):
        value = doc.get(field)
        if value:
            return {field: value}
    return {}


def stable_article_key(doc: dict[str, Any]) -> str:
    for field in ("article_id", "source_external_key", "canonical_url", "url"):
        value = str(doc.get(field) or "").strip()
        if value:
            return safe_name(value)
    digest = hashlib.sha256(json_util.dumps(doc, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return digest[:32]


def article_object_path(root: Path, published_at: str, key: str) -> Path:
    year = published_at[:4] if len(published_at) >= 4 and published_at[:4].isdigit() else "unknown"
    month = published_at[5:7] if len(published_at) >= 7 and published_at[5:7].isdigit() else "unknown"
    return root / year / month / f"{key}.json"


def safe_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)
    if len(cleaned) > 96:
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
        cleaned = f"{cleaned[:79]}_{digest}"
    return cleaned.strip("._-") or hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def unpack_if_needed(path: Path) -> Path:
    if path.is_dir():
        return path
    if not path.name.endswith(".tar.gz"):
        raise SystemExit(f"unsupported bundle path: {path}")
    target = path.with_suffix("").with_suffix("")
    if target.exists():
        return target
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "r:gz") as archive:
        archive.extractall(target.parent)
    inner = target
    if not (inner / "manifest.json").exists():
        matches = [item for item in target.parent.iterdir() if item.is_dir() and (item / "manifest.json").exists()]
        if matches:
            inner = max(matches, key=lambda item: item.stat().st_mtime)
    return inner


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def import_script() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 /opt/NewsAnalysis/scripts/export_news_bundle.py import .
"""


def export_script() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail
cd /opt/NewsAnalysis
python3 scripts/export_news_bundle.py export --source guardian --limit 8000 --order oldest --output-dir exports
"""


def readme_text(manifest: dict[str, Any]) -> str:
    return f"""# NewsAnalysis Guardian Export Bundle

Format: `{manifest["bundle_format"]}`
Source: `{manifest["source_name"]}`
Documents: `{manifest["count"]}`
Index: `{manifest["index_file"]}`

Each article is stored as one standalone JSON object under `objects/`, so a single
article can be restored by downloading only its JSON file plus the small index.

Import on a NewsAnalysis server:

```bash
./import.sh
```

Re-export the same shape on a server:

```bash
./export_guardian_8000.sh
```
"""


if __name__ == "__main__":
    raise SystemExit(main())
