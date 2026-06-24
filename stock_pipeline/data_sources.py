from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT
from .kaipanla import KAIPANLA_FEATURES, list_kaipanla_records
from .stock_storage import list_local_stock_summaries
from .utils import ensure_dir, read_json, timestamp, write_json


DATA_SOURCE_CONFIG_PATH = PROJECT_ROOT / "local_data" / "data_sources.json"


@dataclass(frozen=True)
class DataSourceProvider:
    key: str
    label: str
    status: str
    description: str
    capabilities: list[str]
    limitations: str = ""


@dataclass(frozen=True)
class StandardDataType:
    key: str
    label: str
    category: str
    description: str
    providers: list[str]
    priority: list[str]


DEFAULT_PROVIDERS: dict[str, DataSourceProvider] = {
    "local_cache": DataSourceProvider(
        "local_cache",
        "本地缓存",
        "active",
        "读取 local_data、MongoDB 引用和历史保存结果，是分析层的第一优先级。",
        ["stock_profile", "daily_quote", "minute_quote", "analysis_dossier", "news_item"],
    ),
    "kaipanla": DataSourceProvider(
        "kaipanla",
        "开盘啦",
        "active",
        "提供涨停、连板、龙虎榜、板块、情绪、竞价和部分分时数据。",
        ["limit_up_event", "dragon_tiger", "sector_snapshot", "market_sentiment", "capital_flow", "auction_tick"],
    ),
    "tonghuashun": DataSourceProvider(
        "tonghuashun",
        "同花顺",
        "active",
        "当前用于新闻和最新日分钟行情；历史分钟接口已避免作为可信补采来源。",
        ["news_item", "minute_quote"],
        "分钟历史接口可能静默返回最新日，历史补采必须校验 actual_date。",
    ),
    "tencent_fallback": DataSourceProvider(
        "tencent_fallback",
        "腾讯行情兜底",
        "active",
        "仅在东方财富 K 线接口异常时用于补齐日/周/月行情，记录会标记 source=tencent_fallback。",
        ["daily_quote"],
        "只作为行情兜底，不提供财务和估值资料包。",
    ),
    "eastmoney": DataSourceProvider(
        "eastmoney",
        "东方财富",
        "active",
        "Tushare 封存后的默认市场与财务资料包来源，提供股票基础信息、行情、估值和财务摘要。",
        ["stock_profile", "daily_quote", "finance_summary", "valuation", "sector_snapshot"],
    ),
    "akshare": DataSourceProvider(
        "akshare",
        "AkShare",
        "planned",
        "候选聚合源，用于补齐公开市场数据，接入前需要逐接口验证稳定性。",
        ["stock_profile", "daily_quote", "finance_summary", "index_quote"],
    ),
    "tushare": DataSourceProvider(
        "tushare",
        "Tushare",
        "archived",
        "旧资料包来源，默认封存。只保留历史本地数据读取和必要的回滚入口。",
        ["stock_profile", "daily_quote", "finance_statement", "valuation", "moneyflow"],
        "不再作为新抓取的默认来源；需要稳定 token 时才手动启用。",
    ),
}


STANDARD_DATA_TYPES: dict[str, StandardDataType] = {
    "stock_profile": StandardDataType("stock_profile", "股票基础信息", "股票", "代码、名称、行业、市场、上市状态等。", ["local_cache", "eastmoney", "akshare", "tushare"], ["local_cache", "eastmoney", "akshare", "tushare"]),
    "daily_quote": StandardDataType("daily_quote", "日行情", "行情", "日 K、涨跌幅、成交量、成交额和换手率等。", ["local_cache", "eastmoney", "tencent_fallback", "akshare", "tushare"], ["local_cache", "eastmoney", "tencent_fallback", "akshare", "tushare"]),
    "minute_quote": StandardDataType("minute_quote", "分钟行情", "行情", "个股、板块、指数分钟级走势。", ["local_cache", "tonghuashun", "kaipanla"], ["local_cache", "tonghuashun", "kaipanla"]),
    "limit_up_event": StandardDataType("limit_up_event", "涨停/连板事件", "事件", "涨停、连板梯队、反包、炸板和市场强度。", ["kaipanla", "local_cache"], ["local_cache", "kaipanla"]),
    "dragon_tiger": StandardDataType("dragon_tiger", "龙虎榜", "事件", "上榜股票、席位买卖和个股明细。", ["kaipanla", "local_cache"], ["local_cache", "kaipanla"]),
    "sector_snapshot": StandardDataType("sector_snapshot", "板块快照", "板块", "板块排行、成分股、资金、强度和分时。", ["kaipanla", "local_cache", "eastmoney"], ["local_cache", "kaipanla", "eastmoney"]),
    "market_sentiment": StandardDataType("market_sentiment", "市场情绪", "市场", "涨跌停、上涨下跌家数、情绪热度等。", ["kaipanla", "local_cache"], ["local_cache", "kaipanla"]),
    "capital_flow": StandardDataType("capital_flow", "资金流", "资金", "主力资金、大单资金和板块资金。", ["kaipanla", "eastmoney", "tushare", "local_cache"], ["local_cache", "kaipanla", "eastmoney", "tushare"]),
    "news_item": StandardDataType("news_item", "新闻", "新闻", "财经、公司、行业、宏观新闻证据。", ["local_cache", "tonghuashun"], ["local_cache", "tonghuashun"]),
    "finance_summary": StandardDataType("finance_summary", "财务摘要", "财务", "利润、资产负债、现金流和关键财务指标。", ["eastmoney", "akshare", "tushare", "local_cache"], ["local_cache", "eastmoney", "akshare", "tushare"]),
    "valuation": StandardDataType("valuation", "估值指标", "财务", "PE、PB、市值、换手率等。", ["eastmoney", "akshare", "tushare", "local_cache"], ["local_cache", "eastmoney", "akshare", "tushare"]),
}


def data_source_snapshot(settings: Any | None = None) -> dict[str, Any]:
    config = _load_config()
    providers = [_provider_payload(provider, config, settings) for provider in DEFAULT_PROVIDERS.values()]
    types = [_data_type_payload(item, providers) for item in STANDARD_DATA_TYPES.values()]
    coverage = _coverage_snapshot()
    return {
        "providers": providers,
        "types": types,
        "coverage": coverage,
        "summary": {
            "provider_count": len(providers),
            "active_count": sum(1 for item in providers if item.get("status") == "active"),
            "archived_count": sum(1 for item in providers if item.get("status") == "archived"),
            "planned_count": sum(1 for item in providers if item.get("status") == "planned"),
            "standard_type_count": len(types),
        },
        "updated_at": config.get("updated_at") or "",
    }


def configure_data_sources(updates: dict[str, Any], updated_by: str = "admin") -> dict[str, Any]:
    config = _load_config()
    provider_updates = updates.get("providers") or {}
    if not isinstance(provider_updates, dict):
        raise ValueError("providers 必须是对象。")
    providers = config.setdefault("providers", {})
    for key, patch in provider_updates.items():
        source = str(key).strip()
        if source not in DEFAULT_PROVIDERS:
            raise ValueError(f"未知数据源：{source}")
        if not isinstance(patch, dict):
            continue
        current = providers.setdefault(source, {})
        if "status" in patch:
            status = str(patch.get("status") or "").strip()
            if status not in {"active", "archived", "planned", "disabled"}:
                raise ValueError(f"{source} 状态不正确：{status}")
            current["status"] = status
        if "priority" in patch:
            current["priority"] = max(1, int(patch.get("priority") or 100))
    config["updated_at"] = timestamp()
    config["updated_by"] = updated_by
    ensure_dir(DATA_SOURCE_CONFIG_PATH.parent)
    write_json(DATA_SOURCE_CONFIG_PATH, config)
    return data_source_snapshot()


def provider_status(key: str) -> str:
    provider = DEFAULT_PROVIDERS.get(key)
    if not provider:
        return "missing"
    override = (_load_config().get("providers") or {}).get(key) or {}
    return str(override.get("status") or provider.status)


def provider_available(key: str) -> bool:
    return provider_status(key) == "active"


def _load_config() -> dict[str, Any]:
    if not DATA_SOURCE_CONFIG_PATH.exists():
        return {"version": 1, "providers": {}, "updated_at": ""}
    try:
        data = read_json(DATA_SOURCE_CONFIG_PATH)
    except Exception:
        return {"version": 1, "providers": {}, "updated_at": ""}
    if not isinstance(data, dict):
        return {"version": 1, "providers": {}, "updated_at": ""}
    data.setdefault("version", 1)
    data.setdefault("providers", {})
    return data


def _provider_payload(provider: DataSourceProvider, config: dict[str, Any], settings: Any | None) -> dict[str, Any]:
    override = (config.get("providers") or {}).get(provider.key) or {}
    payload = asdict(provider)
    payload["status"] = override.get("status") or provider.status
    payload["priority"] = int(override.get("priority") or _default_priority(provider.key))
    payload["configured"] = _provider_configured(provider.key, settings)
    return payload


def _data_type_payload(item: StandardDataType, providers: list[dict[str, Any]]) -> dict[str, Any]:
    status_by_key = {provider["key"]: provider["status"] for provider in providers}
    active = [key for key in item.priority if status_by_key.get(key) == "active"]
    payload = asdict(item)
    payload["active_providers"] = active
    payload["primary_provider"] = active[0] if active else ""
    payload["needs_provider"] = not bool(active)
    return payload


def _coverage_snapshot() -> dict[str, Any]:
    stock_summary = list_local_stock_summaries()
    try:
        kaipanla_records = list_kaipanla_records(limit=500).get("items", [])
    except Exception:
        kaipanla_records = []
    feature_counts: dict[str, int] = {}
    for record in kaipanla_records:
        feature = str(record.get("feature") or "")
        if feature:
            feature_counts[feature] = feature_counts.get(feature, 0) + 1
    return {
        "local_stock_count": stock_summary.get("count", 0),
        "local_dataset_rows": stock_summary.get("total_dataset_rows", 0),
        "local_minute_rows": stock_summary.get("total_minute_rows", 0),
        "kaipanla_record_count": len(kaipanla_records),
        "kaipanla_feature_count": len(KAIPANLA_FEATURES),
        "kaipanla_recorded_features": len(feature_counts),
        "top_kaipanla_features": sorted(
            [{"feature": key, "count": count} for key, count in feature_counts.items()],
            key=lambda item: item["count"],
            reverse=True,
        )[:8],
    }


def _provider_configured(key: str, settings: Any | None) -> bool:
    if key == "tushare":
        return bool(getattr(settings, "tushare_token", ""))
    if key in {"local_cache", "kaipanla", "tonghuashun", "tencent_fallback"}:
        return True
    return False


def _default_priority(key: str) -> int:
    return {
        "local_cache": 10,
        "kaipanla": 20,
        "tonghuashun": 30,
        "tencent_fallback": 50,
        "eastmoney": 60,
        "akshare": 70,
        "tushare": 100,
    }.get(key, 100)
