from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pymongo

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from stock_pipeline.market_dimensions import MARKET_COLLECTIONS, MARKET_DATABASE, NEWS_DATABASE, STOCK_COLLECTIONS, STOCK_DATABASE
from stock_pipeline.ths_minute import build_config as build_mongo_config


SOURCE_LABELS = {
    "guardian": "Guardian 新闻",
    "tonghuashun": "同花顺新闻",
    "eastmoney": "东方财富",
    "bloomberg": "Bloomberg 新闻",
    "politico": "Politico 新闻",
    "pytdx_history": "通达信历史分时",
    "tdx": "通达信分时",
    "ths": "同花顺分时",
}


@dataclass
class ReportRow:
    source: str
    data_type: str
    total_count: int
    server_count: int
    cold_count: int
    server_storage_bytes: int
    note: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a read-only server data inventory report.")
    parser.add_argument("--output", default="", help="Write Markdown report to this path. Defaults to stdout only.")
    parser.add_argument("--json", action="store_true", help="Also print the raw JSON payload after the Markdown report.")
    parser.add_argument("--mongo-db", default=MARKET_DATABASE, help="Database used to build the authenticated Mongo URI.")
    parser.add_argument("--quiet", action="store_true", help="Do not print progress messages to stderr.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    progress = Progress(enabled=not args.quiet)
    progress("连接 MongoDB")
    config = build_mongo_config(database=args.mongo_db, collection=MARKET_COLLECTIONS["minute_buckets"])
    client = pymongo.MongoClient(config.mongo_uri, serverSelectionTimeoutMS=8000)
    try:
        payload = build_report_payload(client, progress=progress)
    finally:
        client.close()

    progress("渲染 Markdown 报告")
    markdown = render_markdown(payload)
    print(markdown)
    if args.output:
        progress(f"写入报告文件：{args.output}")
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(markdown + "\n", encoding="utf-8")
    if args.json:
        print("\n```json")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        print("```")
    return 0


class Progress:
    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self.step = 0

    def __call__(self, message: str) -> None:
        if not self.enabled:
            return
        self.step += 1
        print(f"[server-data-audit] {self.step}. {message}", file=sys.stderr, flush=True)


def build_report_payload(client: pymongo.MongoClient, *, progress: Progress) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    business_rows: list[ReportRow] = []
    collection_rows: list[dict[str, Any]] = []

    progress("打开业务数据库：news / market_data / stock_data")
    news_db = client[NEWS_DATABASE]
    market_db = client[MARKET_DATABASE]
    stock_db = client[STOCK_DATABASE]

    progress("统计新闻数据和冷新闻索引")
    raw_stats = collection_stats(news_db, "raw_articles")
    raw_by_source = group_counts(news_db["raw_articles"], "source_name")
    cold_by_source = group_counts(news_db["cold_article_index"], "source_name")
    for source in sorted(set(raw_by_source) | set(cold_by_source)):
        server_count = raw_by_source.get(source, 0)
        cold_count = cold_by_source.get(source, 0)
        business_rows.append(
            ReportRow(
                source=label_for_source(source),
                data_type="新闻数据",
                total_count=server_count + cold_count,
                server_count=server_count,
                cold_count=cold_count,
                server_storage_bytes=estimated_storage(raw_stats, server_count),
                note="news.raw_articles / news.cold_article_index",
            )
        )

    articles_stats = collection_stats(news_db, "articles")
    articles_count = int(articles_stats.get("count") or 0)
    if articles_count:
        business_rows.append(
            ReportRow(
                source="标准化新闻库",
                data_type="新闻数据",
                total_count=articles_count,
                server_count=articles_count,
                cold_count=0,
                server_storage_bytes=storage_total_bytes(articles_stats),
                note="news.articles",
            )
        )

    progress("统计股票分时热数据和百度网盘冷备份索引")
    minute_bucket_stats = collection_stats(market_db, MARKET_COLLECTIONS["minute_buckets"])
    minute_index_stats = collection_stats(market_db, MARKET_COLLECTIONS["minute_day_index"])
    minute_sources = sorted(
        set(market_db[MARKET_COLLECTIONS["minute_buckets"]].distinct("source"))
        | set(market_db[MARKET_COLLECTIONS["minute_day_index"]].distinct("source"))
    )
    for source in minute_sources:
        if not source:
            continue
        server_count = market_db[MARKET_COLLECTIONS["minute_buckets"]].count_documents({"source": source})
        cold_count = market_db[MARKET_COLLECTIONS["minute_day_index"]].count_documents(
            {"source": source, "storage_object": "stock_year_jsonl", "upload_status": "uploaded"}
        )
        total_count = max(server_count, cold_count)
        business_rows.append(
            ReportRow(
                source=label_for_source(source),
                data_type="股票分时",
                total_count=total_count,
                server_count=server_count,
                cold_count=cold_count,
                server_storage_bytes=estimated_storage(minute_bucket_stats, server_count) + estimated_storage(minute_index_stats, cold_count),
                note="market_data.minute_day_buckets + stock_minute_day_index",
            )
        )

    progress("统计开盘啦市场行情数据")
    kaipanla_stats = collection_stats(market_db, MARKET_COLLECTIONS["kaipanla_results"])
    kaipanla_count = int(kaipanla_stats.get("count") or 0)
    if kaipanla_count:
        business_rows.append(
            ReportRow(
                source="开盘啦",
                data_type="市场行情",
                total_count=kaipanla_count,
                server_count=kaipanla_count,
                cold_count=0,
                server_storage_bytes=storage_total_bytes(kaipanla_stats),
                note="market_data.kaipanla_results",
            )
        )

    progress("统计股票热数据、资料包、元数据和覆盖索引")
    stock_rows_stats = collection_stats(stock_db, STOCK_COLLECTIONS["rows"])
    stock_packages_stats = collection_stats(stock_db, STOCK_COLLECTIONS["packages"])
    stock_metadata_stats = collection_stats(stock_db, STOCK_COLLECTIONS["metadata"])
    stock_daily_coverage_stats = collection_stats(stock_db, STOCK_COLLECTIONS["daily_coverage"])
    stock_rows_count = int(stock_rows_stats.get("count") or 0)
    if stock_rows_count:
        business_rows.append(
            ReportRow(
                source="股票日K与指标",
                data_type="股票热数据",
                total_count=stock_rows_count,
                server_count=stock_rows_count,
                cold_count=0,
                server_storage_bytes=storage_total_bytes(stock_rows_stats),
                note="stock_data.stock_dataset_rows",
            )
        )
    stock_packages_count = int(stock_packages_stats.get("count") or 0)
    if stock_packages_count:
        business_rows.append(
            ReportRow(
                source="股票资料包",
                data_type="股票热数据",
                total_count=stock_packages_count,
                server_count=stock_packages_count,
                cold_count=0,
                server_storage_bytes=storage_total_bytes(stock_packages_stats),
                note="stock_data.stock_packages",
            )
        )
    stock_metadata_count = int(stock_metadata_stats.get("count") or 0)
    if stock_metadata_count:
        business_rows.append(
            ReportRow(
                source="股票基础信息",
                data_type="股票元数据",
                total_count=stock_metadata_count,
                server_count=stock_metadata_count,
                cold_count=0,
                server_storage_bytes=storage_total_bytes(stock_metadata_stats),
                note="stock_data.stock_metadata",
            )
        )
    stock_daily_coverage_count = int(stock_daily_coverage_stats.get("count") or 0)
    if stock_daily_coverage_count:
        business_rows.append(
            ReportRow(
                source="日K覆盖索引",
                data_type="覆盖索引",
                total_count=stock_daily_coverage_count,
                server_count=stock_daily_coverage_count,
                cold_count=0,
                server_storage_bytes=storage_total_bytes(stock_daily_coverage_stats),
                note="stock_data.stock_daily_coverage",
            )
        )

    progress("统计 Mongo 各集合存储占用")
    for database_name in [MARKET_DATABASE, STOCK_DATABASE, NEWS_DATABASE]:
        db = client[database_name]
        for collection_name in sorted(db.list_collection_names()):
            stats = collection_stats(db, collection_name)
            collection_rows.append(
                {
                    "database": database_name,
                    "collection": collection_name,
                    "count": int(stats.get("count") or 0),
                    "size_bytes": int(stats.get("size") or 0),
                    "storage_bytes": int(stats.get("storageSize") or 0),
                    "index_bytes": int(stats.get("totalIndexSize") or 0),
                    "total_storage_bytes": storage_total_bytes(stats),
                }
            )

    return {
        "generated_at": generated_at,
        "business_rows": [row.__dict__ for row in sorted(business_rows, key=lambda item: (item.data_type, item.source))],
        "collection_rows": sorted(collection_rows, key=lambda item: item["total_storage_bytes"], reverse=True),
        "totals": {
            "server_storage_bytes": sum(row.server_storage_bytes for row in business_rows),
            "server_count": sum(row.server_count for row in business_rows),
            "cold_count": sum(row.cold_count for row in business_rows),
        },
    }


def collection_stats(db: Any, collection_name: str) -> dict[str, Any]:
    if collection_name not in db.list_collection_names():
        return {"count": 0, "size": 0, "storageSize": 0, "totalIndexSize": 0}
    return db.command("collStats", collection_name)


def group_counts(collection: Any, field: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in collection.aggregate(
        [
            {"$group": {"_id": f"${field}", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ],
        allowDiskUse=True,
    ):
        key = str(row.get("_id") or "unknown")
        result[key] = int(row.get("count") or 0)
    return result


def estimated_storage(stats: dict[str, Any], count: int) -> int:
    total_count = int(stats.get("count") or 0)
    if count <= 0 or total_count <= 0:
        return 0
    return int(storage_total_bytes(stats) * (count / total_count))


def storage_total_bytes(stats: dict[str, Any]) -> int:
    return int(stats.get("storageSize") or 0) + int(stats.get("totalIndexSize") or 0)


def label_for_source(source: str) -> str:
    return SOURCE_LABELS.get(source, source or "unknown")


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# 服务器数据自查报告",
        "",
        f"- 生成时间：`{payload['generated_at']}`",
        f"- 服务器存储估算合计：`{format_bytes(payload['totals']['server_storage_bytes'])}`",
        f"- 服务器热/在线记录合计：`{format_int(payload['totals']['server_count'])}`",
        f"- 冷备份索引记录合计：`{format_int(payload['totals']['cold_count'])}`",
        "",
        "## 业务数据总览",
        "",
        "| 数据源 | 类型 | 总条 | 服务器存储 | 冷备份条数 | 占据服务器存储 | 说明 |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in payload["business_rows"]:
        lines.append(
            "| {source} | {data_type} | {total_count} | {server_count} | {cold_count} | {storage} | {note} |".format(
                source=escape_cell(row["source"]),
                data_type=escape_cell(row["data_type"]),
                total_count=format_int(row["total_count"]),
                server_count=format_int(row["server_count"]),
                cold_count=format_int(row["cold_count"]),
                storage=format_bytes(row["server_storage_bytes"]),
                note=escape_cell(row.get("note") or ""),
            )
        )

    lines.extend(
        [
            "",
            "## Mongo 集合占用",
            "",
            "| 数据库 | 集合 | 文档数 | 数据大小 | 存储文件 | 索引 | 存储+索引 |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in payload["collection_rows"]:
        lines.append(
            "| {database} | {collection} | {count} | {size} | {storage} | {index} | {total} |".format(
                database=escape_cell(row["database"]),
                collection=escape_cell(row["collection"]),
                count=format_int(row["count"]),
                size=format_bytes(row["size_bytes"]),
                storage=format_bytes(row["storage_bytes"]),
                index=format_bytes(row["index_bytes"]),
                total=format_bytes(row["total_storage_bytes"]),
            )
        )
    return "\n".join(lines)


def format_int(value: int) -> str:
    return f"{int(value):,}"


def format_bytes(value: int) -> str:
    size = float(max(0, int(value or 0)))
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def escape_cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(main())
