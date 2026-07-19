from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DataKeySpec:
    key: str
    domain: str
    label: str
    storage: str
    owner: str
    temperature: str


@dataclass(frozen=True)
class FetchMethodSpec:
    key: str
    data_key: str
    label: str
    route: str
    resource: str
    default_provider: str
    status: str = "active"
    notes: str = ""


DATA_KEYS: dict[str, DataKeySpec] = {
    "stock.package": DataKeySpec(
        key="stock.package",
        domain="stock",
        label="股票资料包",
        storage="stock_data.stock_packages",
        owner="datahub",
        temperature="hot",
    ),
    "stock.daily_k": DataKeySpec(
        key="stock.daily_k",
        domain="stock",
        label="股票日K与指标",
        storage="stock_data.stock_dataset_rows / stock_daily_coverage",
        owner="datahub",
        temperature="hot",
    ),
    "stock.minute": DataKeySpec(
        key="stock.minute",
        domain="stock",
        label="股票历史分时",
        storage="market_data.minute_day_buckets / stock_minute_day_index / Baidu Netdisk",
        owner="datahub",
        temperature="cold",
    ),
    "market.kaipanla": DataKeySpec(
        key="market.kaipanla",
        domain="market",
        label="开盘啦行情",
        storage="market_data.kaipanla_results",
        owner="datahub",
        temperature="hot",
    ),
    "news.raw_article": DataKeySpec(
        key="news.raw_article",
        domain="news",
        label="新闻原文",
        storage="news.raw_articles",
        owner="newscrawler",
        temperature="hot",
    ),
    "ops.audit": DataKeySpec(
        key="ops.audit",
        domain="ops",
        label="审计与健康检查",
        storage="local_data / reports / ops snapshots",
        owner="backend",
        temperature="runtime",
    ),
}


FETCH_METHODS: dict[str, FetchMethodSpec] = {
    "stock.package.sync": FetchMethodSpec(
        key="stock.package.sync",
        data_key="stock.package",
        label="同步股票资料包（AkShare 默认，东方财富/腾讯校验补齐）",
        route="/api/sync-stock-data",
        resource="heavy_io",
        default_provider="akshare",
        notes="AkShare 作为公开数据主源；东方财富和腾讯用于正确性验证、字段补齐和行情兜底。Tushare 仅保留历史兼容，不作为新功能默认依赖。",
    ),
    "stock.daily_k.sync": FetchMethodSpec(
        key="stock.daily_k.sync",
        data_key="stock.daily_k",
        label="立即执行每日股票数据更新",
        route="/api/admin/daily-market-scheduler:run_now",
        resource="heavy_io",
        default_provider="akshare",
    ),
    "stock.minute.backfill": FetchMethodSpec(
        key="stock.minute.backfill",
        data_key="stock.minute",
        label="补抓分钟行情（外部行情源/MongoDB）",
        route="/api/sync-ths-market-data",
        resource="heavy_io",
        default_provider="pytdx_history",
    ),
    "stock.minute.market_fetch": FetchMethodSpec(
        key="stock.minute.market_fetch",
        data_key="stock.minute",
        label="启动分钟行情补采",
        route="/api/admin/market-fetch/start",
        resource="heavy_io",
        default_provider="pytdx_history",
    ),
    "stock.storage.repair": FetchMethodSpec(
        key="stock.storage.repair",
        data_key="stock.daily_k",
        label="补齐异常股票存储数据",
        route="/api/admin/stock-storage-repair",
        resource="heavy_io",
        default_provider="akshare",
    ),
    "market.kaipanla.run": FetchMethodSpec(
        key="market.kaipanla.run",
        data_key="market.kaipanla",
        label="立即执行开盘啦数据抓取",
        route="/api/admin/kaipanla/scheduler:run_now",
        resource="normal_io",
        default_provider="kaipanla",
    ),
    "market.kaipanla.feature.run": FetchMethodSpec(
        key="market.kaipanla.feature.run",
        data_key="market.kaipanla",
        label="立即执行开盘啦单项抓取",
        route="/api/admin/kaipanla/run",
        resource="normal_io",
        default_provider="kaipanla",
    ),
    "news.library.refetch": FetchMethodSpec(
        key="news.library.refetch",
        data_key="news.raw_article",
        label="重新抓取新闻并补充到新闻库",
        route="/api/admin/news-library/refetch",
        resource="normal_io",
        default_provider="newscrawler",
        notes="DataHub 只读 NewsCrawler 产物；重抓应通过 NewsCrawler 边界处理。",
    ),
    "news.library.translate": FetchMethodSpec(
        key="news.library.translate",
        data_key="news.raw_article",
        label="调用百度翻译生成 Guardian 中文译文",
        route="/api/admin/news-library/translate",
        resource="normal_io",
        default_provider="baidu_translate",
    ),
    "news.failure.retry": FetchMethodSpec(
        key="news.failure.retry",
        data_key="news.raw_article",
        label="重抓新闻失败 item 并归档仍失败的链接",
        route="/api/admin/news-crawler/failure-action",
        resource="normal_io",
        default_provider="newscrawler",
    ),
    "analysis.single.run": FetchMethodSpec(
        key="analysis.single.run",
        data_key="stock.package",
        label="生成分析前的数据同步与模型调用",
        route="/api/analyze",
        resource="model_io",
        default_provider="deepseek",
    ),
    "analysis.multi_agent.run": FetchMethodSpec(
        key="analysis.multi_agent.run",
        data_key="stock.package",
        label="多 Agent 分析前的数据同步与模型调用",
        route="/api/multi-agent-analyze",
        resource="model_io",
        default_provider="deepseek",
    ),
}


DATA_FETCH_ACTIONS = {spec.route: spec.label for spec in FETCH_METHODS.values() if spec.route}

SPIDER_SOURCES = (
    {
        "id": "ths_market",
        "name": "分钟行情",
        "data_key": "stock.minute",
        "fetch_method": "stock.minute.market_fetch",
        "description": "指定股票分钟行情补抓，默认通达信历史分钟 K，写入 MongoDB 和本地资料包",
    },
)


def data_key_snapshot() -> list[dict[str, str]]:
    return [spec.__dict__.copy() for spec in DATA_KEYS.values()]


def fetch_method_snapshot() -> list[dict[str, str]]:
    return [spec.__dict__.copy() for spec in FETCH_METHODS.values()]
