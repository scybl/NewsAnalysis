from __future__ import annotations

import os
import re
import time
import urllib.parse
from typing import Any


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
        query = _news_query(keywords, days)
        projection = {"_id": 0, "title": 1, "time": 1, "url": 1, "type": 1, "publisher": 1, "summary": 1, "content": 1}
        rows = list(collection.find(query, projection).sort("time", pymongo.DESCENDING).limit(max(1, min(50, limit))))
        return {
            "enabled": True,
            "database": database,
            "collection": collection_name,
            "keywords": keywords,
            "items": [_public_news_item(row, keywords) for row in rows],
            "error": "",
        }
    except Exception as exc:  # noqa: BLE001 - news context should not block analysis
        return {"enabled": False, "keywords": keywords, "items": [], "error": str(exc)}
    finally:
        if client:
            client.close()


def _mongo_uri() -> str:
    if os.getenv("MONGODB_URI"):
        return os.getenv("MONGODB_URI", "")
    host = os.getenv("MONGO_HOST", "localhost")
    port = int(os.getenv("MONGO_PORT", "27017"))
    username = os.getenv("MONGO_USER", "")
    password = os.getenv("MONGO_PASSWORD", "")
    auth_source = os.getenv("MONGO_AUTHSOURCE", "admin")
    if username and password:
        user = urllib.parse.quote_plus(username)
        passwd = urllib.parse.quote_plus(password)
        return f"mongodb://{user}:{passwd}@{host}:{port}/?authSource={auth_source}"
    return f"mongodb://{host}:{port}/"


def _news_query(keywords: list[str], days: int) -> dict[str, Any]:
    escaped = [re.escape(item) for item in keywords if item]
    pattern = "|".join(escaped[:24])
    clauses = [{"title": {"$regex": pattern, "$options": "i"}}]
    clauses.append({"content": {"$regex": pattern, "$options": "i"}})
    clauses.append({"summary": {"$regex": pattern, "$options": "i"}})
    query: dict[str, Any] = {"$or": clauses}
    if days > 0:
        cutoff = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - days * 86400))
        query["time"] = {"$gte": cutoff}
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
