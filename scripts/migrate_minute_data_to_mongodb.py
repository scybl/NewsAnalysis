from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from stock_pipeline.analysis_frameworks import build_all_analysis_dossiers
from stock_pipeline.dossier import build_dossier
from stock_pipeline.minute_storage import MINUTE_DATASET_SOURCES, build_minute_reference
from stock_pipeline.ths_minute import build_config
from stock_pipeline.utils import read_json, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="将本地分钟行情 JSON 迁移为 MongoDB 引用。")
    parser.add_argument("--apply", action="store_true", help="确认修改资料包并删除本地分钟行情 JSON。")
    args = parser.parse_args()

    try:
        import pymongo
    except ImportError as exc:
        raise RuntimeError("缺少 pymongo，无法验证 MongoDB 数据。") from exc

    config = build_config()
    client = pymongo.MongoClient(config.mongo_uri, serverSelectionTimeoutMS=5000)
    collection = client[config.database][config.collection]
    client.admin.command("ping")
    changed_files = 0
    deleted_files = 0
    released_bytes = 0
    skipped: list[str] = []

    try:
        for full_path in sorted((PROJECT_ROOT / "local_data").glob("*/**/full_data.json")):
            full_data = read_json(full_path)
            ts_code = str(full_data.get("ts_code") or full_path.parents[1].name)
            datasets = full_data.setdefault("datasets", {})
            references = full_data.setdefault("external_datasets", {})
            removable = []
            changed = False

            for dataset, source in MINUTE_DATASET_SOURCES.items():
                local_rows = datasets.get(dataset)
                local_count = len(local_rows) if isinstance(local_rows, list) else 0
                dataset_collection = collection
                if dataset == "ths_intraday_minutes":
                    legacy_collection = client[config.database]["ths_intraday_minutes"]
                    primary_count = collection.count_documents({"ts_code": ts_code, "source": source})
                    legacy_count = legacy_collection.count_documents({"ts_code": ts_code})
                    if legacy_count > primary_count:
                        dataset_collection = legacy_collection
                reference = build_minute_reference(dataset_collection, ts_code, dataset=dataset, source=source)
                raw_path = full_path.parent / "raw" / f"{dataset}.json"
                has_local_copy = local_count > 0 or raw_path.exists()
                if not has_local_copy and not references.get(dataset):
                    continue
                if local_count and reference["row_count"] < local_count:
                    skipped.append(
                        f"{full_path}: {dataset} 本地 {local_count} 行，MongoDB 仅 {reference['row_count']} 行"
                    )
                    continue
                if reference["row_count"] <= 0:
                    skipped.append(f"{full_path}: {dataset} 在 MongoDB 中没有数据")
                    continue
                references[dataset] = reference
                if dataset in datasets:
                    datasets.pop(dataset)
                    changed = True
                if raw_path.exists():
                    removable.append(raw_path)

            if not changed and not removable:
                continue
            print(f"{'迁移' if args.apply else '将迁移'} {full_path}")
            if not args.apply:
                continue

            write_json(full_path, full_data)
            changed_files += 1
            for raw_path in removable:
                released_bytes += raw_path.stat().st_size
                raw_path.unlink()
                deleted_files += 1

            if full_path.parent.name == "current":
                dossier = build_dossier(full_data)
                write_json(full_path.parent / "dossier.json", dossier)
                for key, analysis_dossier in build_all_analysis_dossiers(dossier).items():
                    write_json(full_path.parent / f"{key}_dossier.json", analysis_dossier)
                metadata_path = full_path.parents[1] / "metadata.json"
                if metadata_path.exists():
                    metadata = read_json(metadata_path)
                    rows = metadata.setdefault("dataset_rows", {})
                    for dataset, reference in references.items():
                        if dataset in MINUTE_DATASET_SOURCES:
                            rows[dataset] = int(reference.get("row_count") or 0)
                    write_json(metadata_path, metadata)
    finally:
        client.close()

    print(
        f"完成：资料包 {changed_files} 个，删除分钟 JSON {deleted_files} 个，"
        f"释放约 {released_bytes / 1024 / 1024:.1f} MB。"
    )
    if skipped:
        print("以下数据因 MongoDB 行数不足而保留：")
        for message in skipped:
            print(f"- {message}")
    return 1 if skipped else 0


if __name__ == "__main__":
    raise SystemExit(main())
