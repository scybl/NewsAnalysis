from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .raw_news import MongoRawNewsRepository

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
    repository = None
    try:
        repository = MongoRawNewsRepository(timeout_ms=1200)
        rows, total = repository.search(
            keywords=keywords,
            start_date=start_date,
            end_date=end_date,
            limit=max(1, min(50, limit)),
        )
        return {
            "enabled": True,
            "database": repository.config.database,
            "collection": repository.config.collection,
            "keywords": keywords,
            "items": [_public_news_item(row, keywords) for row in rows],
            "total": total,
            "date_range": {"start": start_date, "end": end_date},
            "error": "",
        }
    except Exception as exc:  # noqa: BLE001 - news context should not block analysis
        return {"enabled": False, "keywords": keywords, "items": [], "error": str(exc)}
    finally:
        if repository:
            repository.close()


def _public_news_item(row: dict[str, Any], keywords: list[str]) -> dict[str, Any]:
    text = " ".join(str(row.get(key) or "") for key in ("title", "summary", "content"))
    hits = [keyword for keyword in keywords if keyword and keyword.lower() in text.lower()]
    return {
        "title": row.get("title", ""),
        "time": row.get("published_at", ""),
        "type": row.get("section", ""),
        "publisher": row.get("source_name", ""),
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
    for fmt, length in (("%Y%m%d", 8), ("%Y-%m-%d", 10), ("%Y-%m-%d %H:%M:%S", 19)):
        try:
            return datetime.strptime(text[:length], fmt)
        except ValueError:
            continue
    return None


def _trim(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "..."
