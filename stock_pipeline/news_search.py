from __future__ import annotations

import os
import re
import urllib.parse
from datetime import datetime, timedelta
from typing import Any

from .config import PROJECT_ROOT, load_dotenv
from .secret_store import secret_value


load_dotenv(PROJECT_ROOT / ".env")

INDUSTRY_NEWS_TERMS: dict[str, list[str]] = {
    "农业综合": ["能繁母猪", "生猪价格", "猪肉价格", "养殖成本", "猪周期", "饲料价格"],
    "饲料": ["生猪价格", "饲料价格", "豆粕", "玉米价格", "养殖成本"],
    "养殖业": ["能繁母猪", "生猪价格", "猪肉价格", "养殖成本", "猪周期"],
    "电池": ["锂价", "碳酸锂", "动力电池", "储能", "新能源车"],
    "半导体": ["算力", "AI芯片", "先进封装", "国产替代", "半导体周期"],
    "通信设备": ["光模块", "算力", "数据中心", "AI服务器", "通信设备"],
    "化学制品": ["化工品价格", "原材料价格", "产能", "出口", "库存"],
    "医药": ["医保谈判", "集采", "创新药", "临床试验", "医药政策"],
}


COMPANY_NEWS_TERMS: dict[str, list[str]] = {
    "牧原股份": ["秦英林", "秦牧原", "养殖成本", "能繁母猪", "生猪价格", "猪周期"],
    "宁德时代": ["动力电池", "储能", "锂价", "新能源车", "毛利率"],
    "中际旭创": ["光模块", "800G", "1.6T", "AI服务器", "数据中心"],
}


def build_stock_news_keywords(company: dict[str, Any]) -> list[str]:
    name = str(company.get("name") or "").strip()
    ts_code = str(company.get("ts_code") or "").strip()
    symbol = ts_code.split(".")[0] if ts_code else str(company.get("symbol") or "").strip()
    industry = str(company.get("industry") or "").strip()
    keywords = [item for item in (name, symbol, ts_code, industry) if item]
    keywords.extend(COMPANY_NEWS_TERMS.get(name, []))
    for industry_key, terms in INDUSTRY_NEWS_TERMS.items():
        if industry_key and industry_key in industry:
            keywords.extend(terms)
    return _dedupe_keywords(keywords)


def search_related_news(company: dict[str, Any], limit: int = 12, days: int = 45) -> dict[str, Any]:
    keywords = build_stock_news_keywords(company)
    if not keywords:
        return {"enabled": False, "keywords": [], "items": [], "error": "缺少股票关键词。"}
    date_range = _recent_date_range(days)
    return search_news_evidence(company, keywords=keywords, start_date=date_range["start"], end_date=date_range["end"], limit=limit)


def build_news_evidence_context(
    company: dict[str, Any],
    learning_context: dict[str, Any] | None = None,
    *,
    recent_days: int = 60,
    recent_limit: int = 12,
    historical_limit: int = 6,
    max_windows: int = 4,
    window_days: int = 45,
) -> dict[str, Any]:
    keywords = build_stock_news_keywords(company)
    if not keywords:
        return {"enabled": False, "keywords": [], "recent": {"items": []}, "historical_windows": [], "error": "缺少股票关键词。"}

    recent_range = _recent_date_range(recent_days)
    recent = search_news_evidence(company, keywords=keywords, start_date=recent_range["start"], end_date=recent_range["end"], limit=recent_limit)
    windows = []
    for case in _historical_news_windows(learning_context or {}, max_windows=max_windows, window_days=window_days):
        evidence = search_news_evidence(
            company,
            keywords=keywords,
            start_date=case["start_date"],
            end_date=case["end_date"],
            limit=historical_limit,
        )
        windows.append(
            {
                **case,
                "items": evidence.get("items", []),
                "total": evidence.get("total", 0),
                "error": evidence.get("error", ""),
            }
        )
    return {
        "enabled": bool(recent.get("enabled")),
        "database": recent.get("database", ""),
        "collection": recent.get("collection", ""),
        "keywords": keywords,
        "recent": {
            "date_range": recent.get("date_range", {}),
            "items": recent.get("items", []),
            "total": recent.get("total", 0),
        },
        "items": recent.get("items", []),
        "historical_windows": windows,
        "error": recent.get("error", ""),
        "instruction": "优先使用同一标的、同一行业关键词、对应时间窗内的新闻作为事件证据；若无命中，必须说明数据库没有检索到新闻支撑。",
    }


def search_news_evidence(
    company: dict[str, Any],
    *,
    keywords: list[str] | None = None,
    start_date: str = "",
    end_date: str = "",
    limit: int = 12,
) -> dict[str, Any]:
    keywords = _dedupe_keywords(keywords or build_stock_news_keywords(company))
    if not keywords:
        return {"enabled": False, "keywords": [], "items": [], "error": "缺少股票关键词。"}
    try:
        import pymongo
    except ImportError as exc:
        return {"enabled": False, "keywords": keywords, "items": [], "error": f"缺少 pymongo：{exc}"}

    uri = _mongo_uri()
    database = os.getenv("MONGODB_DATABASE") or os.getenv("MONGO_DB") or "news"
    collection_name = os.getenv("MONGODB_COLLECTION") or os.getenv("MONGO_COLLECTION") or "articles"
    client = None
    try:
        client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=1200, socketTimeoutMS=1200)
        collection = client[database][collection_name]
        query = _news_query(keywords, start_date=start_date, end_date=end_date)
        projection = {"_id": 0, "title": 1, "time": 1, "url": 1, "type": 1, "publisher": 1, "summary": 1, "content": 1}
        total = collection.count_documents(query)
        rows = list(collection.find(query, projection).sort("time", pymongo.DESCENDING).limit(max(1, min(50, limit))))
        return {
            "enabled": True,
            "database": database,
            "collection": collection_name,
            "keywords": keywords,
            "items": [_public_news_item(row, keywords) for row in rows],
            "total": total,
            "date_range": {"start": start_date, "end": end_date},
            "error": "",
        }
    except Exception as exc:  # noqa: BLE001 - news context should not block analysis
        return {"enabled": False, "keywords": keywords, "items": [], "error": str(exc)}
    finally:
        if client:
            client.close()


def _mongo_uri() -> str:
    direct_uri = secret_value("mongo.uri", ("MONGODB_URI", "MONGO_URI"))
    if direct_uri:
        return direct_uri
    host = os.getenv("MONGO_HOST", "localhost")
    port = int(os.getenv("MONGO_PORT", "27017"))
    username = secret_value("mongo.user", ("MONGO_USER",))
    password = secret_value("mongo.password", ("MONGO_PASSWORD",))
    auth_source = os.getenv("MONGO_AUTHSOURCE", "admin")
    if username and password:
        user = urllib.parse.quote_plus(username)
        passwd = urllib.parse.quote_plus(password)
        return f"mongodb://{user}:{passwd}@{host}:{port}/?authSource={auth_source}"
    return f"mongodb://{host}:{port}/"


def _news_query(keywords: list[str], *, start_date: str = "", end_date: str = "") -> dict[str, Any]:
    escaped = [re.escape(item) for item in keywords if item]
    pattern = "|".join(escaped[:24])
    clauses = [{"title": {"$regex": pattern, "$options": "i"}}]
    clauses.append({"content": {"$regex": pattern, "$options": "i"}})
    clauses.append({"summary": {"$regex": pattern, "$options": "i"}})
    query: dict[str, Any] = {"$or": clauses}
    time_range = _time_filter(start_date, end_date)
    if time_range:
        query["time"] = time_range
    return query


def _public_news_item(row: dict[str, Any], keywords: list[str]) -> dict[str, Any]:
    text = " ".join(str(row.get(key) or "") for key in ("title", "summary", "content"))
    hits = [keyword for keyword in keywords if keyword and keyword.lower() in text.lower()]
    return {
        "title": row.get("title", ""),
        "time": row.get("time", ""),
        "type": row.get("type", ""),
        "publisher": row.get("publisher", ""),
        "url": row.get("url", ""),
        "matched_keywords": hits[:8],
        "excerpt": _trim(row.get("summary") or row.get("content") or "", 220),
    }


def _dedupe_keywords(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        result.append(text)
    return result


def _historical_news_windows(learning_context: dict[str, Any], *, max_windows: int, window_days: int) -> list[dict[str, Any]]:
    windows = []
    for case in learning_context.get("similar_cases", [])[:max_windows]:
        trade_date = str(case.get("trade_date") or "")
        center = _parse_date(trade_date)
        if not center:
            continue
        start = center - timedelta(days=window_days)
        end = center + timedelta(days=window_days)
        windows.append(
            {
                "trade_date": center.strftime("%Y%m%d"),
                "start_date": start.strftime("%Y-%m-%d"),
                "end_date": end.strftime("%Y-%m-%d"),
                "similarity": case.get("similarity"),
                "outcome_class": case.get("outcome_class", ""),
                "forward_returns": case.get("forward_returns", {}),
                "reason": "historical_similarity_window",
            }
        )
    return windows


def _time_filter(start_date: str, end_date: str) -> dict[str, str]:
    result: dict[str, str] = {}
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    if start:
        result["$gte"] = start.strftime("%Y-%m-%d 00:00:00")
    if end:
        result["$lte"] = end.strftime("%Y-%m-%d 23:59:59")
    return result


def _recent_date_range(days: int) -> dict[str, str]:
    end = datetime.now()
    start = end - timedelta(days=max(0, days))
    return {"start": start.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d")}


def _parse_date(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[: len(fmt)], fmt)
        except ValueError:
            continue
    return None


def _trim(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "..."
