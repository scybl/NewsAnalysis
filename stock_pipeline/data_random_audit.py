from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any

from .market_dimensions import MARKET_COLLECTIONS, MARKET_DATABASE, NEWS_DATABASE, STOCK_COLLECTIONS, STOCK_DATABASE
from .minute_cold_storage import read_cached_or_downloaded_day
from .utils import normalize_ts_code


EXPECTED_MINUTE_ROWS = 240
REQUIRED_NEWS_FIELDS = ("title", "url", "source_name")
REQUIRED_DAILY_FIELDS = ("open", "high", "low", "close", "vol")


def build_random_audit_payload(
    client: Any,
    *,
    sample_size: int = 20,
    seed: int | None = None,
    cold_read_samples: int = 0,
    progress: Any | None = None,
) -> dict[str, Any]:
    sample_size = max(1, min(int(sample_size or 20), 200))
    cold_read_samples = max(0, min(int(cold_read_samples or 0), 10))
    rng = random.Random(seed)
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    report_seed = seed if seed is not None else rng.randrange(1, 10_000_000_000)
    rng.seed(report_seed)

    news_db = client[NEWS_DATABASE]
    market_db = client[MARKET_DATABASE]
    stock_db = client[STOCK_DATABASE]

    checks: list[dict[str, Any]] = []

    _progress(progress, "统计服务器与冷备份整体一致性")
    checks.append(_check_inventory_consistency(news_db, market_db, stock_db))

    _progress(progress, "随机抽检股票分时冷热链路")
    checks.append(_check_minute_data(market_db, sample_size=sample_size, rng=rng, cold_read_samples=cold_read_samples))

    _progress(progress, "随机抽检股票日K覆盖和字段质量")
    checks.append(_check_daily_k(stock_db, sample_size=sample_size, rng=rng))

    _progress(progress, "随机抽检股票资料包")
    checks.append(_check_stock_packages(stock_db, sample_size=sample_size))

    _progress(progress, "随机抽检新闻数据")
    checks.append(_check_news(news_db, sample_size=sample_size))

    _progress(progress, "随机抽检开盘啦数据")
    checks.append(_check_kaipanla(market_db, sample_size=sample_size))

    summary = _summarize_checks(checks)
    return {
        "ok": summary["status"] != "danger",
        "generated_at": generated_at,
        "seed": report_seed,
        "sample_size": sample_size,
        "cold_read_samples": cold_read_samples,
        "summary": summary,
        "checks": checks,
    }


def _check_inventory_consistency(news_db: Any, market_db: Any, stock_db: Any) -> dict[str, Any]:
    minute_index = market_db[MARKET_COLLECTIONS["minute_day_index"]]
    minute_buckets = market_db[MARKET_COLLECTIONS["minute_buckets"]]
    minute_coverage = market_db[MARKET_COLLECTIONS["minute_coverage"]]
    stock_packages = stock_db[STOCK_COLLECTIONS["packages"]]
    stock_metadata = stock_db[STOCK_COLLECTIONS["metadata"]]
    stock_daily_coverage = stock_db[STOCK_COLLECTIONS["daily_coverage"]]

    metrics = {
        "minute_cold_index_days_estimate": _estimated_count(minute_index),
        "minute_cold_uploaded_stocks": _estimated_count(minute_coverage),
        "minute_hot_bucket_days_estimate": _estimated_count(minute_buckets),
        "minute_coverage_stocks_estimate": _estimated_count(minute_coverage),
        "daily_coverage_stocks_estimate": _estimated_count(stock_daily_coverage),
        "stock_packages_estimate": _estimated_count(stock_packages),
        "stock_metadata_estimate": _estimated_count(stock_metadata),
        "raw_news_estimate": _estimated_count(news_db["raw_articles"]),
        "kaipanla_records_estimate": _estimated_count(market_db[MARKET_COLLECTIONS["kaipanla_results"]]),
    }
    anomalies: list[dict[str, Any]] = []
    if metrics["minute_coverage_stocks_estimate"] and metrics["minute_cold_uploaded_stocks"] < metrics["minute_coverage_stocks_estimate"]:
        anomalies.append(
            _anomaly(
                "minute_cold_lag",
                "分时冷备份股票数少于覆盖索引股票数",
                expected=metrics["minute_coverage_stocks_estimate"],
                actual=metrics["minute_cold_uploaded_stocks"],
            )
        )
    if metrics["stock_packages_estimate"] and metrics["daily_coverage_stocks_estimate"] < int(metrics["stock_packages_estimate"] * 0.9):
        anomalies.append(
            _anomaly(
                "daily_stock_count_low",
                "有资料包的股票中，日K覆盖股票数偏低",
                expected=f">= {int(metrics['stock_packages_estimate'] * 0.9)}",
                actual=metrics["daily_coverage_stocks_estimate"],
            )
        )
    if abs(metrics["stock_metadata_estimate"] - metrics["stock_packages_estimate"]) > max(10, int(metrics["stock_packages_estimate"] * 0.05)):
        anomalies.append(
            _anomaly(
                "metadata_package_mismatch",
                "股票元数据数量与资料包数量差异较大",
                expected=metrics["stock_packages_estimate"],
                actual=metrics["stock_metadata_estimate"],
            )
        )
    return _check("inventory_consistency", "整体一致性", "检查服务器热数据、Mongo 索引和冷备份进度是否大体一致。", metrics, anomalies)


def _check_minute_data(market_db: Any, *, sample_size: int, rng: random.Random, cold_read_samples: int) -> dict[str, Any]:
    minute_index = market_db[MARKET_COLLECTIONS["minute_day_index"]]
    minute_buckets = market_db[MARKET_COLLECTIONS["minute_buckets"]]
    match = {"upload_status": "uploaded", "source": "pytdx_history"}
    samples = _sample_minute_index_docs(minute_index, market_db[MARKET_COLLECTIONS["minute_coverage"]], match, sample_size, rng)
    anomalies: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    cold_reads_done = 0
    stale_hot_uploaded = 0
    missing_remote = 0
    missing_hash = 0

    for doc in samples:
        ts_code = str(doc.get("ts_code") or "")
        trade_date = str(doc.get("trade_date") or "")
        row_count = int(doc.get("row_count") or 0)
        hot = minute_buckets.find_one({"source": doc.get("source"), "ts_code": ts_code, "trade_date": trade_date}, {"_id": 0, "row_count": 1})
        item = {
            "ts_code": ts_code,
            "trade_date": trade_date,
            "storage_object": doc.get("storage_object") or "",
            "upload_status": doc.get("upload_status") or "",
            "indexed_rows": row_count,
            "hot_rows": int((hot or {}).get("row_count") or 0),
            "cold_read_rows": None,
            "result": "ok",
        }
        if hot:
            stale_hot_uploaded += 1
        if not doc.get("remote_path"):
            missing_remote += 1
            item["result"] = "failed"
            anomalies.append(_anomaly("minute_missing_remote_path", "分时冷备份索引缺少 remote_path", sample={"ts_code": ts_code, "trade_date": trade_date}))
        if not doc.get("sha256"):
            missing_hash += 1
            item["result"] = "warning"
            anomalies.append(_anomaly("minute_missing_sha256", "分时冷备份索引缺少 sha256，无法做文件校验", sample={"ts_code": ts_code, "trade_date": trade_date}))
        if row_count and row_count != EXPECTED_MINUTE_ROWS:
            item["result"] = "warning"
            anomalies.append(
                _anomaly(
                    "minute_row_count_unexpected",
                    "分时单日行数不是预期 240 行",
                    sample={"ts_code": ts_code, "trade_date": trade_date},
                    expected=EXPECTED_MINUTE_ROWS,
                    actual=row_count,
                )
            )
        if cold_reads_done < cold_read_samples:
            try:
                rows = read_cached_or_downloaded_day(minute_index, ts_code=ts_code, trade_date=trade_date, source=str(doc.get("source") or "pytdx_history"))
                item["cold_read_rows"] = len(rows)
                cold_reads_done += 1
                if len(rows) != row_count:
                    item["result"] = "failed"
                    anomalies.append(
                        _anomaly(
                            "minute_cold_read_mismatch",
                            "冷备份取回行数与索引行数不一致",
                            sample={"ts_code": ts_code, "trade_date": trade_date},
                            expected=row_count,
                            actual=len(rows),
                        )
                    )
            except Exception as exc:  # noqa: BLE001 - report, do not stop the audit
                item["cold_read_rows"] = "failed"
                item["result"] = "failed"
                anomalies.append(_anomaly("minute_cold_read_failed", "分时冷备份取回失败", sample={"ts_code": ts_code, "trade_date": trade_date}, error=str(exc)))
        details.append(item)

    metrics = {
        "sampled_days": len(samples),
        "cold_read_samples": cold_reads_done,
        "indexed_days_estimate": minute_index.estimated_document_count(),
        "uploaded_stocks": market_db[MARKET_COLLECTIONS["minute_coverage"]].count_documents({"source": "pytdx_history", "has_minute_data": True}),
        "hot_uploaded_sample_hits": stale_hot_uploaded,
        "sample_missing_remote_path_days": missing_remote,
        "sample_missing_sha256_days": missing_hash,
    }
    return _check("minute_cold_chain", "股票分时冷热链路", "随机抽取已上传分时索引，检查行数、远端路径、哈希、热桶残留和可选冷备份取回。", metrics, anomalies, details)


def _check_daily_k(stock_db: Any, *, sample_size: int, rng: random.Random) -> dict[str, Any]:
    rows = stock_db[STOCK_COLLECTIONS["rows"]]
    metadata = stock_db[STOCK_COLLECTIONS["metadata"]]
    coverage = stock_db[STOCK_COLLECTIONS["daily_coverage"]]
    codes = [normalize_ts_code(str(code)) for code in metadata.distinct("ts_code") if str(code or "").strip()]
    rng.shuffle(codes)
    selected = codes[:sample_size]
    anomalies: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    stocks_with_missing = 0
    missing_days = 0
    internal_missing_days = 0
    tail_missing_days = 0
    for ts_code in selected:
        latest = rows.find_one({"snapshot": "current", "dataset": "daily", "ts_code": ts_code}, {"_id": 0}, sort=[("trade_date", -1)])
        coverage_doc = coverage.find_one({"ts_code": ts_code}, {"_id": 0}) or {}
        latest_row = (latest or {}).get("row") if isinstance((latest or {}).get("row"), dict) else (latest or {})
        missing_fields = [field for field in REQUIRED_DAILY_FIELDS if latest and latest_row.get(field) in (None, "")]
        stock_metadata = metadata.find_one({"ts_code": ts_code}, {"_id": 0, "metadata": 1}) or {}
        metadata_payload = stock_metadata.get("metadata") or {}
        missing_count = int(coverage_doc.get("missing_days") or 0)
        internal_missing_count = int(coverage_doc.get("internal_missing_days") or 0)
        tail_missing_count = int(coverage_doc.get("tail_missing_days") or 0)
        missing_days += missing_count
        internal_missing_days += internal_missing_count
        tail_missing_days += tail_missing_count
        if missing_count:
            stocks_with_missing += 1
        detail = {
            "ts_code": ts_code,
            "name": str((metadata_payload.get("stock_basic") or {}).get("name") or metadata_payload.get("name") or ""),
            "coverage_status": coverage_doc.get("status") or ("not_indexed" if not coverage_doc else ""),
            "latest_indexed_date": (latest or {}).get("trade_date") or "",
            "latest_complete_date": coverage_doc.get("latest_complete_date") or "",
            "missing_days": missing_count,
            "internal_missing_days": internal_missing_count,
            "tail_missing_days": tail_missing_count,
            "missing_samples": coverage_doc.get("missing_samples") or [],
            "field_missing": missing_fields,
        }
        if missing_count:
            anomalies.append(_anomaly("daily_k_gap", "日K存在缺口", sample=detail, actual=missing_count))
        if not latest:
            anomalies.append(_anomaly("daily_k_no_latest_row", "日K样本没有最新记录", sample={"ts_code": ts_code}))
        if not coverage_doc:
            anomalies.append(_anomaly("daily_k_coverage_missing", "日K覆盖索引缺失，无法判断是否有缺口", sample={"ts_code": ts_code}))
        elif missing_fields:
            anomalies.append(_anomaly("daily_k_required_field_missing", "日K最新记录关键字段为空", sample={"ts_code": ts_code}, fields=missing_fields))
        details.append(detail)
    metrics = {
        "sampled_stocks": len(selected),
        "daily_total_stocks": len(codes),
        "stocks_with_missing": stocks_with_missing,
        "missing_days": missing_days,
        "internal_missing_days": internal_missing_days,
        "tail_missing_days": tail_missing_days,
    }
    return _check("daily_k_coverage", "股票日K覆盖", "随机抽取日K股票，读取已有覆盖索引并检查最新记录关键字段。", metrics, anomalies, details)


def _check_stock_packages(stock_db: Any, *, sample_size: int) -> dict[str, Any]:
    packages = stock_db[STOCK_COLLECTIONS["packages"]]
    samples = _sample_docs(packages, {"snapshot": "current"}, sample_size, {"_id": 0, "ts_code": 1, "snapshot": 1, "metadata": 1, "full_data": 1, "external_datasets": 1, "dataset_counts": 1, "synced_at": 1})
    anomalies: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    for doc in samples:
        ts_code = str(doc.get("ts_code") or "")
        full_data = doc.get("full_data") or {}
        datasets = full_data.get("datasets") or {}
        daily_rows = datasets.get("daily") or []
        external = full_data.get("external_datasets") or doc.get("external_datasets") or {}
        dataset_counts = doc.get("dataset_counts") or {}
        detail = {
            "ts_code": ts_code,
            "dataset_count": len(datasets),
            "daily_rows": len(daily_rows) if isinstance(daily_rows, list) else 0,
            "daily_count_index": int(dataset_counts.get("daily") or 0),
            "has_minute_reference": "pytdx_history_minutes" in external,
            "synced_at": str(doc.get("synced_at") or ""),
            "result": "ok",
        }
        if not ts_code:
            detail["result"] = "failed"
            anomalies.append(_anomaly("stock_package_missing_code", "股票资料包缺少 ts_code"))
        if not daily_rows:
            detail["result"] = "failed"
            anomalies.append(_anomaly("stock_package_missing_daily", "股票资料包缺少 daily 数据集", sample={"ts_code": ts_code}))
        if len(datasets) < 3:
            detail["result"] = "warning"
            anomalies.append(_anomaly("stock_package_dataset_low", "股票资料包数据集数量偏少", sample={"ts_code": ts_code}, actual=len(datasets)))
        details.append(detail)
    metrics = {"sampled_packages": len(samples), "total_packages": packages.count_documents({"snapshot": "current"})}
    return _check("stock_packages", "股票资料包", "随机抽取 Mongo 股票资料包，检查 daily 数据集、数据集数量和分时外部引用。", metrics, anomalies, details)


def _check_news(news_db: Any, *, sample_size: int) -> dict[str, Any]:
    raw = news_db["raw_articles"]
    samples = _sample_docs(raw, {}, sample_size, {"_id": 0, "source_name": 1, "title": 1, "url": 1, "content": 1, "published_at": 1, "created_at": 1})
    anomalies: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for doc in samples:
        missing = [field for field in REQUIRED_NEWS_FIELDS if not doc.get(field)]
        content_len = len(str(doc.get("content") or ""))
        url = str(doc.get("url") or "")
        detail = {
            "source_name": doc.get("source_name") or "",
            "title": str(doc.get("title") or "")[:80],
            "url": url,
            "content_chars": content_len,
            "published_at": str(doc.get("published_at") or ""),
            "result": "ok",
        }
        if missing:
            detail["result"] = "failed"
            anomalies.append(_anomaly("news_required_field_missing", "新闻关键字段缺失", sample=detail, fields=missing))
        if content_len < 80:
            detail["result"] = "warning"
            anomalies.append(_anomaly("news_content_too_short", "新闻正文过短，可能抓取失败", sample=detail, actual=content_len))
        if url and url in seen_urls:
            detail["result"] = "warning"
            anomalies.append(_anomaly("news_duplicate_url_in_sample", "新闻抽样中出现重复 URL", sample=detail))
        seen_urls.add(url)
        details.append(detail)
    metrics = {"sampled_articles": len(samples), "total_articles": raw.count_documents({}), "sources": raw.distinct("source_name")}
    return _check("news_raw_articles", "新闻原始库", "随机抽取新闻，检查标题、URL、正文长度、发布时间和抽样内重复。", metrics, anomalies, details)


def _check_kaipanla(market_db: Any, *, sample_size: int) -> dict[str, Any]:
    collection = market_db[MARKET_COLLECTIONS["kaipanla_results"]]
    samples = _sample_docs(collection, {}, sample_size, {"_id": 0})
    anomalies: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    for doc in samples:
        feature = str(doc.get("feature") or doc.get("feature_id") or doc.get("name") or "")
        date = str(doc.get("date") or doc.get("trade_date") or doc.get("display_date") or "")
        status = str(doc.get("status") or "")
        payload = doc.get("payload") or doc.get("data") or doc.get("result")
        detail = {
            "feature": feature,
            "date": date,
            "status": status,
            "has_payload": payload not in (None, "", [], {}),
            "result": "ok",
        }
        if not feature:
            detail["result"] = "warning"
            anomalies.append(_anomaly("kaipanla_feature_missing", "开盘啦记录缺少功能名称", sample=detail))
        if not date:
            detail["result"] = "warning"
            anomalies.append(_anomaly("kaipanla_date_missing", "开盘啦记录缺少日期", sample=detail))
        if not detail["has_payload"]:
            detail["result"] = "failed"
            anomalies.append(_anomaly("kaipanla_payload_empty", "开盘啦记录 payload 为空", sample=detail))
        details.append(detail)
    latest = collection.find_one({}, {"_id": 0, "date": 1, "trade_date": 1, "display_date": 1, "saved_at": 1}, sort=[("saved_at", -1)])
    metrics = {"sampled_records": len(samples), "total_records": collection.count_documents({}), "latest_record": latest or {}}
    return _check("kaipanla_records", "开盘啦数据", "随机抽取开盘啦结果，检查功能、日期和 payload 是否存在。", metrics, anomalies, details)


def _sample_docs(collection: Any, match: dict[str, Any], size: int, project: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    try:
        total = collection.count_documents(match or {})
        if total <= 0:
            return []
        rng = random.Random(total + int(size))
        docs: list[dict[str, Any]] = []
        used_offsets: set[int] = set()
        attempts = 0
        target = min(int(size), total)
        while len(docs) < target and attempts < target * 8:
            attempts += 1
            offset = rng.randrange(total)
            if offset in used_offsets and total > target:
                continue
            used_offsets.add(offset)
            doc = collection.find(match or {}, project or {"_id": 0}).skip(offset).limit(1)
            docs.extend(list(doc))
        return docs
    except Exception:
        cursor = collection.find(match or {}, project or {"_id": 0}).limit(max(1, int(size)))
        return list(cursor)


def _estimated_count(collection: Any) -> int:
    try:
        return int(collection.estimated_document_count() or 0)
    except Exception:
        return 0


def _sample_minute_index_docs(day_index: Any, coverage: Any, match: dict[str, Any], size: int, rng: random.Random) -> list[dict[str, Any]]:
    projection = {
        "_id": 0,
        "source": 1,
        "ts_code": 1,
        "trade_date": 1,
        "row_count": 1,
        "status": 1,
        "upload_status": 1,
        "storage_object": 1,
        "remote_path": 1,
        "relative_path": 1,
        "sha256": 1,
    }
    codes = [
        str(item.get("ts_code") or "")
        for item in coverage.find({"source": "pytdx_history", "has_minute_data": True}, {"_id": 0, "ts_code": 1})
        if item.get("ts_code")
    ]
    rng.shuffle(codes)
    docs: list[dict[str, Any]] = []
    for ts_code in codes:
        stock_match = {**match, "ts_code": ts_code}
        count = day_index.count_documents(stock_match)
        if count <= 0:
            continue
        offset = rng.randrange(count)
        doc = day_index.find(stock_match, projection).skip(offset).limit(1)
        docs.extend(list(doc))
        if len(docs) >= int(size):
            break
    return docs


def _check(
    key: str,
    title: str,
    description: str,
    metrics: dict[str, Any],
    anomalies: list[dict[str, Any]],
    details: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    failures = sum(1 for item in anomalies if item.get("severity") == "danger")
    warnings = sum(1 for item in anomalies if item.get("severity") == "warning")
    status = "danger" if failures else "warning" if warnings else "ok"
    return {
        "key": key,
        "title": title,
        "description": description,
        "status": status,
        "metrics": metrics,
        "anomalies": anomalies,
        "details": details or [],
        "summary": {"anomalies": len(anomalies), "failures": failures, "warnings": warnings},
    }


def _anomaly(code: str, message: str, *, severity: str | None = None, **fields: Any) -> dict[str, Any]:
    danger_codes = {"minute_missing_remote_path", "minute_cold_read_mismatch", "minute_cold_read_failed", "daily_k_no_latest_row", "stock_package_missing_code", "stock_package_missing_daily", "kaipanla_payload_empty"}
    payload = {"code": code, "message": message, "severity": severity or ("danger" if code in danger_codes else "warning")}
    payload.update({key: value for key, value in fields.items() if value not in (None, "", [], {})})
    return payload


def _summarize_checks(checks: list[dict[str, Any]]) -> dict[str, Any]:
    danger = sum(1 for item in checks if item.get("status") == "danger")
    warning = sum(1 for item in checks if item.get("status") == "warning")
    ok = sum(1 for item in checks if item.get("status") == "ok")
    anomalies = sum(int((item.get("summary") or {}).get("anomalies") or 0) for item in checks)
    return {
        "status": "danger" if danger else "warning" if warning else "ok",
        "checks": len(checks),
        "ok_checks": ok,
        "warning_checks": warning,
        "danger_checks": danger,
        "anomalies": anomalies,
    }


def _progress(progress: Any | None, message: str) -> None:
    if progress is not None:
        progress(message)
