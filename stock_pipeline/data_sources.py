from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .config import PROJECT_ROOT
from .kaipanla import KAIPANLA_FEATURES, list_kaipanla_records
from .stock_storage import list_local_stock_summaries
from .utils import ensure_dir, read_json, timestamp, write_json


DATA_SOURCE_CONFIG_PATH = PROJECT_ROOT / "local_data" / "data_sources.json"
HIDDEN_PROVIDER_KEYS: set[str] = set()
STANDARD_TABLE_HIDDEN_PROVIDER_KEYS = {"tushare"}


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
    "stock_data": DataSourceProvider(
        "stock_data",
        "股票资料包",
        "active",
        "个股维度主存储，读取 stock_data 数据库中的股票资料包、日 K、财务、估值和分析资料包。",
        ["stock_profile", "stock_daily_quote", "finance_summary", "valuation", "analysis_dossier"],
    ),
    "market_data": DataSourceProvider(
        "market_data",
        "市场行情",
        "active",
        "市场维度主存储，读取 market_data 数据库中的分时桶、开盘啦市场情绪、板块、龙虎榜、ETF 和竞价数据。",
        ["market_minute_quote", "limit_up_event", "dragon_tiger", "sector_snapshot", "market_sentiment", "capital_flow", "auction_tick"],
    ),
    "news_data": DataSourceProvider(
        "news_data",
        "市场新闻",
        "active",
        "新闻维度主存储，读取 news 数据库中的标准化新闻原文和采集运行记录。",
        ["news_item"],
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
        ["news_item", "market_minute_quote"],
        "分钟历史接口可能静默返回最新日，历史补采必须校验 actual_date。",
    ),
    "tencent_fallback": DataSourceProvider(
        "tencent_fallback",
        "腾讯行情兜底",
        "active",
        "仅在东方财富 K 线接口异常时用于补齐日/周/月行情，记录会标记 source=tencent_fallback。",
        ["stock_daily_quote"],
        "只作为行情兜底，不提供财务和估值资料包。",
    ),
    "eastmoney": DataSourceProvider(
        "eastmoney",
        "东方财富",
        "active",
        "Tushare 封存后的默认市场与财务资料包来源，提供股票基础信息、行情、估值、财务摘要、股东、融资融券、资金流、分红和公告等。",
        ["stock_profile", "stock_daily_quote", "finance_summary", "valuation", "sector_snapshot", "capital_flow", "shareholder", "corporate_action", "disclosure"],
    ),
    "akshare": DataSourceProvider(
        "akshare",
        "AkShare",
        "planned",
        "候选聚合源，用于补齐公开市场数据，接入前需要逐接口验证稳定性。",
        ["stock_profile", "stock_daily_quote", "finance_summary", "index_quote"],
    ),
    "tushare": DataSourceProvider(
        "tushare",
        "Tushare",
        "archived",
        "旧资料包来源，默认封存。只保留历史本地数据读取和必要的回滚入口。",
        ["stock_profile", "stock_daily_quote", "finance_statement", "valuation", "moneyflow"],
        "不再作为新抓取的默认来源；需要稳定 token 时才手动启用。",
    ),
}


STANDARD_DATA_TYPES: dict[str, StandardDataType] = {
    "stock_profile": StandardDataType("stock_profile", "股票基础信息", "个股", "代码、名称、行业、市场、上市状态等。", ["stock_data", "eastmoney", "akshare", "tushare"], ["stock_data", "eastmoney", "akshare", "tushare"]),
    "stock_daily_quote": StandardDataType("stock_daily_quote", "个股日行情", "个股", "个股日 K、涨跌幅、成交量、成交额和换手率等。", ["stock_data", "eastmoney", "tencent_fallback", "akshare", "tushare"], ["stock_data", "eastmoney", "tencent_fallback", "akshare", "tushare"]),
    "finance_summary": StandardDataType("finance_summary", "财务摘要", "个股", "利润、资产负债、现金流和关键财务指标。", ["stock_data", "eastmoney", "akshare", "tushare"], ["stock_data", "eastmoney", "akshare", "tushare"]),
    "valuation": StandardDataType("valuation", "估值指标", "个股", "PE、PB、市值、换手率等。", ["stock_data", "eastmoney", "akshare", "tushare"], ["stock_data", "eastmoney", "akshare", "tushare"]),
    "market_minute_quote": StandardDataType("market_minute_quote", "分时行情", "市场行情", "个股、板块、指数分钟级走势，作为市场实时结构观察。", ["market_data", "tonghuashun", "kaipanla"], ["market_data", "tonghuashun", "kaipanla"]),
    "limit_up_event": StandardDataType("limit_up_event", "涨停/连板事件", "市场行情", "涨停、连板梯队、反包、炸板和市场强度。", ["market_data", "kaipanla"], ["market_data", "kaipanla"]),
    "dragon_tiger": StandardDataType("dragon_tiger", "龙虎榜", "市场行情", "上榜股票、席位买卖和个股明细。", ["market_data", "kaipanla"], ["market_data", "kaipanla"]),
    "sector_snapshot": StandardDataType("sector_snapshot", "板块快照", "市场行情", "板块排行、成分股、资金、强度和分时。", ["market_data", "kaipanla", "eastmoney"], ["market_data", "kaipanla", "eastmoney"]),
    "market_sentiment": StandardDataType("market_sentiment", "市场情绪", "市场行情", "涨跌停、上涨下跌家数、情绪热度等。", ["market_data", "kaipanla"], ["market_data", "kaipanla"]),
    "capital_flow": StandardDataType("capital_flow", "资金流", "市场行情", "主力资金、大单资金和板块资金。", ["market_data", "kaipanla", "eastmoney", "tushare"], ["market_data", "kaipanla", "eastmoney", "tushare"]),
    "news_item": StandardDataType("news_item", "新闻", "市场新闻", "财经、公司、行业、宏观新闻证据。", ["news_data", "tonghuashun"], ["news_data", "tonghuashun"]),
}


def data_source_snapshot(settings: Any | None = None) -> dict[str, Any]:
    config = _load_config()
    all_providers = [_provider_payload(provider, config, settings) for provider in DEFAULT_PROVIDERS.values()]
    providers = [provider for provider in all_providers if provider.get("key") not in HIDDEN_PROVIDER_KEYS]
    types = [_data_type_payload(item, all_providers) for item in STANDARD_DATA_TYPES.values()]
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
    payload["capabilities"] = [_standard_data_label(key) for key in provider.capabilities]
    return payload


def _data_type_payload(item: StandardDataType, providers: list[dict[str, Any]]) -> dict[str, Any]:
    status_by_key = {provider["key"]: provider["status"] for provider in providers}
    visible_priority = [key for key in item.priority if key not in STANDARD_TABLE_HIDDEN_PROVIDER_KEYS]
    active = [key for key in visible_priority if status_by_key.get(key) == "active"]
    payload = asdict(item)
    payload.pop("key", None)
    payload["providers"] = [_provider_label(key) for key in item.providers if key not in STANDARD_TABLE_HIDDEN_PROVIDER_KEYS]
    payload["priority"] = [_provider_label(key) for key in visible_priority]
    payload["active_providers"] = [_provider_label(key) for key in active]
    payload["primary_provider"] = _provider_label(active[0]) if active else ""
    payload["needs_provider"] = not bool(active)
    return payload


def _provider_label(key: str) -> str:
    provider = DEFAULT_PROVIDERS.get(key)
    return provider.label if provider else key


def _standard_data_label(key: str) -> str:
    item = STANDARD_DATA_TYPES.get(key)
    return item.label if item else key


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
        "stock_count": stock_summary.get("count", 0),
        "stock_dataset_rows": stock_summary.get("total_dataset_rows", 0),
        "market_minute_rows": stock_summary.get("total_minute_rows", 0),
        "market_record_count": len(kaipanla_records),
        "market_feature_count": len(KAIPANLA_FEATURES),
        "market_recorded_features": len(feature_counts),
        "top_kaipanla_features": sorted(
            [{"feature": key, "count": count} for key, count in feature_counts.items()],
            key=lambda item: item["count"],
            reverse=True,
        )[:8],
    }


def _provider_configured(key: str, settings: Any | None) -> bool:
    if key == "tushare":
        return bool(getattr(settings, "tushare_token", ""))
    if key in {"stock_data", "market_data", "news_data", "kaipanla", "tonghuashun", "tencent_fallback", "eastmoney"}:
        return True
    return False


def _default_priority(key: str) -> int:
    return {
        "stock_data": 10,
        "market_data": 10,
        "news_data": 10,
        "kaipanla": 20,
        "tonghuashun": 30,
        "tencent_fallback": 50,
        "eastmoney": 60,
        "akshare": 70,
        "tushare": 100,
    }.get(key, 100)
