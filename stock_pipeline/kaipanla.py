from __future__ import annotations

import inspect
import json
import re
from dataclasses import dataclass, asdict
from datetime import date
from typing import Any

from pymongo import ASCENDING, DESCENDING, MongoClient

from .kaipanla_crawler import KaipanlaCrawler
from .market_dimensions import MARKET_COLLECTIONS, MARKET_DATABASE
from .ths_minute import _mongo_uri
from .utils import timestamp


DEFAULT_DATE = "2026-01-16"
DEFAULT_DB = MARKET_DATABASE
KAIPANLA_COLLECTION = MARKET_COLLECTIONS["kaipanla_results"]
KAIPANLA_OVERVIEW_REPAIR_FEATURES = [
    "consecutive_limit_up",
    "market_limit_up_ladder",
    "new_high_data",
    "sharp_withdrawal",
]


@dataclass(frozen=True)
class KaipanlaFeature:
    key: str
    label: str
    category: str
    description: str
    default_params: dict[str, Any]
    requires: str = ""


KAIPANLA_FEATURES: dict[str, KaipanlaFeature] = {
    "daily_data": KaipanlaFeature("daily_data", "交易日完整数据", "核心数据", "涨跌统计、大盘指数、连板梯队和回撤统计。", {"end_date": DEFAULT_DATE}),
    "new_high_data": KaipanlaFeature("new_high_data", "百日新高", "核心数据", "百日新高股票今日新增数量。", {"end_date": DEFAULT_DATE, "timeout": 20}),
    "market_sentiment": KaipanlaFeature("market_sentiment", "市场情绪统计", "传统接口", "市场涨跌停和情绪概览。", {"date": DEFAULT_DATE}),
    "market_index": KaipanlaFeature("market_index", "大盘指数", "传统接口", "上证指数等指数历史数据。", {"date": DEFAULT_DATE}),
    "limit_up_ladder": KaipanlaFeature("limit_up_ladder", "连板梯队", "传统接口", "基础连板梯队数据。", {"date": DEFAULT_DATE}),
    "sharp_withdrawal": KaipanlaFeature("sharp_withdrawal", "大幅回撤", "传统接口", "大幅回撤股票统计。", {"date": DEFAULT_DATE}),
    "sector_ranking": KaipanlaFeature("sector_ranking", "板块排行", "板块数据", "板块涨跌幅、成交额和主力资金排行。", {"date": DEFAULT_DATE, "index": 0, "timeout": 20}),
    "consecutive_limit_up": KaipanlaFeature("consecutive_limit_up", "连板梯队详细", "连板梯队", "连板梯队、最高板和题材信息。", {"date": DEFAULT_DATE, "timeout": 20}),
    "sector_limit_up_ladder": KaipanlaFeature("sector_limit_up_ladder", "板块连板梯队", "连板梯队", "按板块聚合的连板梯队。", {"date": DEFAULT_DATE, "timeout": 20}),
    "market_limit_up_ladder": KaipanlaFeature("market_limit_up_ladder", "全市场连板梯队", "连板梯队", "全市场实时或历史连板梯队。", {"date": DEFAULT_DATE, "timeout": 20}),
    "historical_broken_limit_up": KaipanlaFeature("historical_broken_limit_up", "历史反包板", "连板梯队", "历史反包板股票列表。", {"date": DEFAULT_DATE, "timeout": 20}),
    "sector_capital_data": KaipanlaFeature("sector_capital_data", "板块资金", "板块数据", "板块主力资金和成交数据。", {"sector_code": "801346", "date": DEFAULT_DATE, "timeout": 20}),
    "sector_strength_ndays": KaipanlaFeature("sector_strength_ndays", "板块 N 日强度", "板块数据", "板块强度近 N 日变化。", {"end_date": DEFAULT_DATE, "num_days": 7, "timeout": 20}),
    "realtime_market_mood": KaipanlaFeature("realtime_market_mood", "实时市场情绪", "实时监控", "实时市场情绪指标。", {"timeout": 20}),
    "realtime_actual_limit_up_down": KaipanlaFeature("realtime_actual_limit_up_down", "实时实际涨跌停", "实时监控", "实时实际涨停和跌停数据。", {"timeout": 20}),
    "realtime_board_stocks": KaipanlaFeature("realtime_board_stocks", "实时板块股票", "实时监控", "实时指定榜单股票。", {"board_type": 1, "timeout": 20}),
    "realtime_all_boards_stocks": KaipanlaFeature("realtime_all_boards_stocks", "实时全部榜单", "实时监控", "实时全部榜单股票。", {"timeout": 20}),
    "board_stocks_count_and_list": KaipanlaFeature("board_stocks_count_and_list", "榜单股票数量和列表", "实时监控", "指定榜单数量和股票列表。", {"board_type": 1, "timeout": 20}),
    "realtime_index_trend": KaipanlaFeature("realtime_index_trend", "实时指数趋势", "指数分时", "指定指数实时趋势。", {"stock_id": "801900", "time": "15:00", "timeout": 20}),
    "realtime_index_list": KaipanlaFeature("realtime_index_list", "实时指数列表", "指数分时", "多个指数实时列表。", {"stock_ids": ["801900"], "timeout": 20}, requires="部分环境可能需要 Token"),
    "realtime_sharp_withdrawal": KaipanlaFeature("realtime_sharp_withdrawal", "实时大幅回撤", "实时监控", "实时大幅回撤股票。", {"timeout": 20}),
    "realtime_rise_fall_analysis": KaipanlaFeature("realtime_rise_fall_analysis", "实时涨跌分析", "实时监控", "实时涨跌分布分析。", {"timeout": 20}),
    "sector_intraday": KaipanlaFeature("sector_intraday", "板块分时", "分时数据", "板块每分钟价格、成交量和成交额。", {"sector_code": "801346", "date": DEFAULT_DATE, "timeout": 20}),
    "sector_volume_turnover": KaipanlaFeature("sector_volume_turnover", "板块成交分时", "分时数据", "板块分时成交量和成交额。", {"sector_code": "801346", "date": DEFAULT_DATE, "timeout": 20}),
    "stock_intraday": KaipanlaFeature("stock_intraday", "个股分时", "分时数据", "个股分时价格、均价和主力净流入。", {"stock_code": "002498", "date": DEFAULT_DATE, "timeout": 20}),
    "stock_big_order_intraday": KaipanlaFeature("stock_big_order_intraday", "个股大单分时", "分时数据", "个股分时大单资金。", {"stock_code": "002498", "date": DEFAULT_DATE, "timeout": 20}),
    "index_intraday": KaipanlaFeature("index_intraday", "指数分时", "指数分时", "指数分钟级走势。", {"index_code": "SH000001", "date": DEFAULT_DATE, "timeout": 20}),
    "plate_news": KaipanlaFeature("plate_news", "板块新闻", "新闻", "指定板块资讯列表。", {"plate_id": "801346", "index": 0, "page_size": 30, "timeout": 20}),
    "plate_news_dataframe": KaipanlaFeature("plate_news_dataframe", "板块新闻表格", "新闻", "多页板块资讯 DataFrame。", {"plate_id": "801346", "max_pages": 1, "page_size": 30, "timeout": 20}),
    "ths_hot_rank": KaipanlaFeature("ths_hot_rank", "同花顺热榜", "扩展数据", "通过浏览器抓取同花顺热榜。", {"headless": True, "wait_time": 5, "timeout": 20, "max_rank": 50}, requires="Selenium/Chrome 环境"),
    "sector_strength": KaipanlaFeature("sector_strength", "板块强度", "板块数据", "指定板块强度值。", {"sector_code": "801346", "date": DEFAULT_DATE, "timeout": 20}),
    "multiple_sectors_strength": KaipanlaFeature("multiple_sectors_strength", "多板块强度", "板块数据", "批量获取多个板块强度。", {"sector_codes": ["801346", "801225"], "date": DEFAULT_DATE, "timeout": 20}),
    "sector_strength_history": KaipanlaFeature("sector_strength_history", "板块强度历史", "板块数据", "指定日期范围的板块强度历史。", {"sector_code": "801346", "start_date": "2026-01-12", "end_date": DEFAULT_DATE, "timeout": 20}),
    "sector_strength_dataframe": KaipanlaFeature("sector_strength_dataframe", "板块强度历史表格", "板块数据", "板块强度历史 DataFrame。", {"sector_code": "801346", "start_date": "2026-01-12", "end_date": DEFAULT_DATE, "timeout": 20}),
    "longhubang_stock_list": KaipanlaFeature("longhubang_stock_list", "龙虎榜列表", "龙虎榜", "指定日期龙虎榜股票列表。", {"date": DEFAULT_DATE, "index": 0, "page_size": 500, "timeout": 20}),
    "longhubang_stock_detail": KaipanlaFeature("longhubang_stock_detail", "龙虎榜详情", "龙虎榜", "指定股票龙虎榜明细。", {"stock_code": "002498", "date": DEFAULT_DATE, "timeout": 20}),
    "longhubang_dataframe": KaipanlaFeature("longhubang_dataframe", "龙虎榜表格", "龙虎榜", "龙虎榜列表 DataFrame。", {"date": DEFAULT_DATE, "timeout": 20}),
    "sector_constituent_stocks": KaipanlaFeature("sector_constituent_stocks", "板块成分股", "板块数据", "指定板块成分股。", {"plate_id": "801346", "date": DEFAULT_DATE, "order": 1, "timeout": 20}),
    "sector_all_stocks": KaipanlaFeature("sector_all_stocks", "板块全部股票", "板块数据", "分页获取板块全部成分股。", {"plate_id": "801346", "date": DEFAULT_DATE, "order": 1, "max_pages": 1, "timeout": 20}),
    "sector_bidding_anomaly": KaipanlaFeature("sector_bidding_anomaly", "板块竞价异动", "竞价数据", "竞价阶段板块异动。", {"date": DEFAULT_DATE, "timeout": 20}),
    "etf_ranking": KaipanlaFeature("etf_ranking", "ETF 排行", "ETF", "ETF 排行分页数据。", {"date": DEFAULT_DATE, "order": 1, "index": 0, "timeout": 20}),
    "all_etf_ranking": KaipanlaFeature("all_etf_ranking", "ETF 全量排行", "ETF", "分页获取 ETF 排行。", {"date": DEFAULT_DATE, "order": 1, "max_pages": 1, "timeout": 20}),
    "stock_call_auction_tick": KaipanlaFeature("stock_call_auction_tick", "个股竞价 Tick", "竞价数据", "东方财富 9:15-9:25 竞价 tick。", {"stock_code": "002498", "date": DEFAULT_DATE, "timeout": 20}),
}


FEATURE_METHODS = {
    "daily_data": "get_daily_data",
    "new_high_data": "get_new_high_data",
    "market_sentiment": "get_market_sentiment",
    "market_index": "get_market_index",
    "limit_up_ladder": "get_limit_up_ladder",
    "sharp_withdrawal": "get_sharp_withdrawal",
    "sector_ranking": "get_sector_ranking",
    "consecutive_limit_up": "get_consecutive_limit_up",
    "sector_limit_up_ladder": "get_sector_limit_up_ladder",
    "market_limit_up_ladder": "get_market_limit_up_ladder",
    "historical_broken_limit_up": "get_historical_broken_limit_up",
    "sector_capital_data": "get_sector_capital_data",
    "sector_strength_ndays": "get_sector_strength_ndays",
    "realtime_market_mood": "get_realtime_market_mood",
    "realtime_actual_limit_up_down": "get_realtime_actual_limit_up_down",
    "realtime_board_stocks": "get_realtime_board_stocks",
    "realtime_all_boards_stocks": "get_realtime_all_boards_stocks",
    "board_stocks_count_and_list": "get_board_stocks_count_and_list",
    "realtime_index_trend": "get_realtime_index_trend",
    "realtime_index_list": "get_realtime_index_list",
    "realtime_sharp_withdrawal": "get_realtime_sharp_withdrawal",
    "realtime_rise_fall_analysis": "get_realtime_rise_fall_analysis",
    "sector_intraday": "get_sector_intraday",
    "sector_volume_turnover": "get_sector_volume_turnover",
    "stock_intraday": "get_stock_intraday",
    "stock_big_order_intraday": "get_stock_big_order_intraday",
    "index_intraday": "get_index_intraday",
    "plate_news": "get_plate_news",
    "plate_news_dataframe": "get_plate_news_dataframe",
    "ths_hot_rank": "get_ths_hot_rank",
    "sector_strength": "get_sector_strength",
    "multiple_sectors_strength": "get_multiple_sectors_strength",
    "sector_strength_history": "get_sector_strength_history",
    "sector_strength_dataframe": "get_sector_strength_dataframe",
    "longhubang_stock_list": "get_longhubang_stock_list",
    "longhubang_stock_detail": "get_longhubang_stock_detail",
    "longhubang_dataframe": "get_longhubang_dataframe",
    "sector_constituent_stocks": "get_sector_constituent_stocks",
    "sector_all_stocks": "get_sector_all_stocks",
    "sector_bidding_anomaly": "get_sector_bidding_anomaly",
    "etf_ranking": "get_etf_ranking",
    "all_etf_ranking": "get_all_etf_ranking",
    "stock_call_auction_tick": "get_stock_call_auction_tick",
}


def list_kaipanla_features() -> list[dict[str, Any]]:
    return [asdict(feature) for feature in KAIPANLA_FEATURES.values()]


def run_kaipanla_feature(
    key: str,
    params: dict[str, Any] | None = None,
    *,
    save: bool = False,
    run_id: str = "",
    trade_date: str = "",
) -> dict[str, Any]:
    if key not in KAIPANLA_FEATURES:
        raise ValueError(f"未知开盘啦功能：{key}")
    method_name = FEATURE_METHODS[key]
    crawler = KaipanlaCrawler()
    method = getattr(crawler, method_name)
    final_params = {**KAIPANLA_FEATURES[key].default_params, **(params or {})}
    final_params = _filter_params(method, final_params)
    started = date.today().isoformat()
    result = method(**final_params)
    payload = {
        "ok": True,
        "feature": asdict(KAIPANLA_FEATURES[key]),
        "method": method_name,
        "params": final_params,
        "run_date": started,
        "result": to_jsonable(result),
    }
    normalized_trade_date = _normalize_date_text(trade_date)
    if normalized_trade_date:
        payload["trade_date"] = normalized_trade_date
    if save:
        payload["saved"] = save_kaipanla_result(key, payload, run_id=run_id)
    return payload


def run_kaipanla_batch(
    feature_keys: list[str],
    params_by_feature: dict[str, dict[str, Any]] | None = None,
    *,
    save: bool = True,
    run_id: str = "",
    trade_date: str = "",
) -> dict[str, Any]:
    selected = [key for key in feature_keys if key in KAIPANLA_FEATURES]
    if not selected:
        raise ValueError("请至少选择一个开盘啦功能。")
    normalized_trade_date = _display_date(trade_date) if trade_date else ""
    results = []
    succeeded = 0
    failed = 0
    for key in selected:
        try:
            params = (params_by_feature or {}).get(key) or {}
            if normalized_trade_date:
                params = _params_with_trade_date(key, params, normalized_trade_date)
            result = run_kaipanla_feature(key, params, save=save, run_id=run_id, trade_date=normalized_trade_date)
            results.append({"feature": key, "ok": True, "saved": result.get("saved", {})})
            succeeded += 1
        except Exception as exc:  # noqa: BLE001 - batch should keep remaining features running
            results.append({"feature": key, "ok": False, "error": str(exc)})
            failed += 1
    return {
        "ok": failed == 0,
        "run_id": run_id,
        "trade_date": normalized_trade_date,
        "total": len(selected),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
    }


def save_kaipanla_result(key: str, payload: dict[str, Any], *, run_id: str = "") -> dict[str, Any]:
    if key not in KAIPANLA_FEATURES:
        raise ValueError(f"未知开盘啦功能：{key}")
    saved_at = timestamp()
    clean_run_id = _safe_name(run_id or saved_at)
    path = f"mongodb://{DEFAULT_DB}/{KAIPANLA_COLLECTION}/{key}/{saved_at}/{clean_run_id}"
    record = {
        "schema": "kaipanla.result.v1",
        "feature": key,
        "label": KAIPANLA_FEATURES[key].label,
        "category": KAIPANLA_FEATURES[key].category,
        "saved_at": saved_at,
        "run_id": run_id or clean_run_id,
        "path": path,
        "payload": payload,
    }
    return save_kaipanla_record(record)


def save_kaipanla_record(record: dict[str, Any], *, database: str = DEFAULT_DB) -> dict[str, Any]:
    key = str(record.get("feature") or "")
    if key not in KAIPANLA_FEATURES:
        raise ValueError(f"未知开盘啦功能：{key}")
    saved_at = str(record.get("saved_at") or timestamp())
    run_id = str(record.get("run_id") or saved_at)
    path = str(record.get("path") or f"mongodb://{database}/{KAIPANLA_COLLECTION}/{key}/{saved_at}/{_safe_name(run_id)}")
    payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
    document = {
        "record_id": _record_id(key, saved_at, run_id),
        "schema": str(record.get("schema") or "kaipanla.result.v1"),
        "feature": key,
        "label": str(record.get("label") or KAIPANLA_FEATURES[key].label),
        "category": str(record.get("category") or KAIPANLA_FEATURES[key].category),
        "saved_at": saved_at,
        "run_id": run_id,
        "path": path,
        "ok": bool(payload.get("ok")),
        "params": payload.get("params", {}) if isinstance(payload, dict) else {},
        "payload": payload,
        "storage": "mongodb",
        "synced_at": timestamp(),
    }
    document["trade_date"] = _record_trade_date(document)
    with _kaipanla_collection(database) as collection:
        collection.update_one({"record_id": document["record_id"]}, {"$set": document}, upsert=True)
    return {"path": path, "saved_at": saved_at, "run_id": run_id, "storage": "mongodb"}


def list_kaipanla_records(limit: int = 80, feature: str = "") -> dict[str, Any]:
    query = {"feature": feature} if feature else {}
    max_limit = max(1, min(500, int(limit or 80)))
    with _kaipanla_collection() as collection:
        cursor = collection.find(
            query,
            {
                "_id": 0,
                "record_id": 1,
                "feature": 1,
                "label": 1,
                "category": 1,
                "saved_at": 1,
                "run_id": 1,
                "path": 1,
                "ok": 1,
                "params": 1,
                "storage": 1,
            },
        ).sort([("saved_at", DESCENDING), ("feature", ASCENDING)]).limit(max_limit)
        items = list(cursor)
    return {"items": items, "count": len(items), "data_dir": f"mongodb://{DEFAULT_DB}/{KAIPANLA_COLLECTION}"}


def kaipanla_daily_overview(target_date: str = "") -> dict[str, Any]:
    requested_date = _normalize_date_text(target_date)
    normalized_date = requested_date
    fallback = False
    with _kaipanla_collection() as collection:
        if not normalized_date:
            normalized_date = _latest_kaipanla_trade_date(collection, require_daily_packet=True)
        records = _kaipanla_records_for_date(collection, normalized_date)
        if requested_date and not _overview_has_daily_packet(records):
            fallback_date = _latest_kaipanla_trade_date(collection, upper_bound=requested_date, require_daily_packet=True)
            if fallback_date and fallback_date != normalized_date:
                normalized_date = fallback_date
                fallback = True
                records = _kaipanla_records_for_date(collection, normalized_date)
    latest_by_feature: dict[str, dict[str, Any]] = {}
    for record in records:
        feature = str(record.get("feature") or "")
        if feature and feature not in latest_by_feature:
            latest_by_feature[feature] = record
    feature_cards = [_feature_card(record) for record in latest_by_feature.values()]
    succeeded = sum(1 for record in latest_by_feature.values() if record.get("ok"))
    failed = sum(1 for record in latest_by_feature.values() if not record.get("ok"))
    return {
        "date": normalized_date,
        "display_date": _display_date(normalized_date),
        "requested_date": requested_date,
        "requested_display_date": _display_date(requested_date),
        "fallback": fallback,
        "coverage": {
            "total_features": len(KAIPANLA_FEATURES),
            "collected_features": len(latest_by_feature),
            "succeeded": succeeded,
            "failed": failed,
            "missing": max(0, len(KAIPANLA_FEATURES) - len(latest_by_feature)),
        },
        "latest_saved_at": max((str(item.get("saved_at") or "") for item in latest_by_feature.values()), default=""),
        "kpis": _overview_kpis(latest_by_feature),
        "sections": {
            "temperature": _overview_section(latest_by_feature, ["daily_data", "market_sentiment", "new_high_data", "sharp_withdrawal"]),
            "limit_up": _overview_section(latest_by_feature, ["consecutive_limit_up", "market_limit_up_ladder", "sector_limit_up_ladder", "historical_broken_limit_up"]),
            "sectors": _overview_section(latest_by_feature, ["sector_ranking", "sector_strength_ndays", "sector_capital_data", "sector_bidding_anomaly"]),
            "capital": _overview_section(latest_by_feature, ["longhubang_dataframe", "longhubang_stock_list"]),
            "etf": _overview_section(latest_by_feature, ["all_etf_ranking", "etf_ranking"]),
            "intraday": _overview_section(latest_by_feature, ["realtime_market_mood", "realtime_rise_fall_analysis", "realtime_actual_limit_up_down", "realtime_sharp_withdrawal"]),
        },
        "features": feature_cards,
        "data_dir": f"mongodb://{DEFAULT_DB}/{KAIPANLA_COLLECTION}",
    }


def _latest_kaipanla_trade_date(collection: Any, *, upper_bound: str = "", require_daily_packet: bool = False) -> str:
    upper = _normalize_date_text(upper_bound)
    query = {"archived": {"$ne": True}}
    if require_daily_packet:
        query["feature"] = "daily_data"
    cursor = collection.find(
        query,
        {"_id": 0, "saved_at": 1, "trade_date": 1, "params": 1, "payload.trade_date": 1},
    ).sort([("saved_at", DESCENDING), ("feature", ASCENDING)]).limit(2000)
    candidates = {
        trade_date
        for record in cursor
        if (trade_date := _record_trade_date(record)) and (not upper or trade_date <= upper)
    }
    if candidates:
        return max(candidates)
    if require_daily_packet:
        return _latest_kaipanla_trade_date(collection, upper_bound=upper)
    if upper:
        return _latest_kaipanla_trade_date(collection)
    return ""


def _overview_has_daily_packet(records: list[dict[str, Any]]) -> bool:
    return any(str(record.get("feature") or "") == "daily_data" and bool(record.get("ok")) for record in records)


def repair_kaipanla_overview_history(target_date: str, *, dry_run: bool = False) -> dict[str, Any]:
    normalized_date = _normalize_date_text(target_date)
    if not normalized_date:
        raise ValueError("请提供需要修复的交易日，例如 2026-06-30。")
    display_date = _display_date(normalized_date)
    params_by_feature = {
        "consecutive_limit_up": {"date": display_date, "timeout": 20},
        "market_limit_up_ladder": {"date": display_date, "timeout": 20},
        "new_high_data": {"end_date": display_date, "timeout": 20},
        "sharp_withdrawal": {"date": display_date},
    }
    live_payloads: dict[str, dict[str, Any]] = {}
    for feature in KAIPANLA_OVERVIEW_REPAIR_FEATURES:
        live_payloads[feature] = run_kaipanla_feature(feature, params_by_feature[feature], save=False)
    live_records = {
        feature: {
            "feature": feature,
            "label": KAIPANLA_FEATURES[feature].label,
            "category": KAIPANLA_FEATURES[feature].category,
            "saved_at": timestamp(),
            "run_id": "live-repair-check",
            "path": "",
            "ok": bool(payload.get("ok")),
            "params": payload.get("params", {}),
            "payload": payload,
        }
        for feature, payload in live_payloads.items()
    }
    kpis = _overview_kpis(live_records)
    kpi_values = {str(item.get("label")): item.get("value") for item in kpis}
    valid = all(_to_number(kpi_values.get(label)) not in (None, 0) for label in ("最高连板", "百日新高", "大幅回撤"))
    if not valid:
        return {
            "ok": False,
            "date": normalized_date,
            "display_date": display_date,
            "dry_run": dry_run,
            "saved": [],
            "archived": 0,
            "kpis": kpis,
            "error": "实时重抓结果未通过有效性检查，已停止修复历史记录。",
        }

    existing_ids: list[str] = []
    with _kaipanla_collection() as collection:
        existing_records = _kaipanla_records_for_date(collection, normalized_date)
        existing_ids = [
            str(record.get("record_id") or "")
            for record in existing_records
            if record.get("feature") in KAIPANLA_OVERVIEW_REPAIR_FEATURES and record.get("record_id")
        ]

    if dry_run:
        return {
            "ok": True,
            "date": normalized_date,
            "display_date": display_date,
            "dry_run": True,
            "saved": [],
            "archived": 0,
            "would_archive": len(existing_ids),
            "kpis": kpis,
        }

    run_id = f"kaipanla_overview_repair_{normalized_date}_{timestamp()}"
    saved = [
        save_kaipanla_result(feature, payload, run_id=run_id)
        for feature, payload in live_payloads.items()
    ]
    archived = 0
    if existing_ids:
        with _kaipanla_collection() as collection:
            result = collection.update_many(
                {"record_id": {"$in": existing_ids}},
                {"$set": {"archived": True, "archived_at": timestamp(), "archive_reason": f"superseded by {run_id}"}},
            )
            archived = int(getattr(result, "modified_count", 0) or 0)
    return {
        "ok": True,
        "date": normalized_date,
        "display_date": display_date,
        "dry_run": False,
        "run_id": run_id,
        "saved": saved,
        "archived": archived,
        "kpis": kpis,
    }


def read_kaipanla_record(path: str) -> dict[str, Any]:
    text = str(path or "").strip()
    if not text:
        raise ValueError("缺少开盘啦记录路径。")
    with _kaipanla_collection() as collection:
        document = collection.find_one(
            {"$or": [{"path": text}, {"record_id": text}]},
            {"_id": 0},
        )
    if not document:
        raise ValueError("开盘啦记录不存在。")
    return {
        "schema": document.get("schema") or "kaipanla.result.v1",
        "feature": document.get("feature", ""),
        "label": document.get("label", ""),
        "category": document.get("category", ""),
        "saved_at": document.get("saved_at", ""),
        "run_id": document.get("run_id", ""),
        "path": document.get("path", ""),
        "payload": document.get("payload", {}),
        "storage": "mongodb",
    }


def validate_kaipanla_integration() -> dict[str, Any]:
    crawler = KaipanlaCrawler()
    methods = {
        name
        for name, value in inspect.getmembers(crawler, predicate=callable)
        if name.startswith("get_") and not name.startswith("_")
    }
    configured = set(FEATURE_METHODS.values())
    missing = sorted(methods - configured)
    unknown = sorted(configured - methods)
    return {
        "ok": not missing and not unknown,
        "feature_count": len(KAIPANLA_FEATURES),
        "method_count": len(methods),
        "missing_methods": missing,
        "unknown_methods": unknown,
        "features": list_kaipanla_features(),
    }


def parse_params(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("--params 必须是 JSON object。")
    return data


def to_jsonable(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    try:
        import pandas as pd
    except Exception:  # pragma: no cover - pandas is a project dependency
        pd = None
    if pd is not None:
        if isinstance(value, pd.DataFrame):
            return {
                "type": "dataframe",
                "columns": list(value.columns),
                "rows": value.to_dict(orient="records"),
                "row_count": int(len(value)),
            }
        if isinstance(value, pd.Series):
            return {
                "type": "series",
                "name": value.name,
                "index": [str(item) for item in value.index],
                "values": [to_jsonable(item) for item in value.tolist()],
            }
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def _kaipanla_records_for_date(collection: Any, normalized_date: str) -> list[dict[str, Any]]:
    compact = normalized_date.replace("-", "")
    dashed = _display_date(normalized_date)
    query: dict[str, Any] = {"archived": {"$ne": True}}
    if compact:
        query = {
            "archived": {"$ne": True},
            "$or": [
                {"trade_date": compact},
                {"saved_at": {"$regex": f"^{compact}"}},
                {"params.date": {"$in": [compact, dashed]}},
                {"params.end_date": {"$in": [compact, dashed]}},
            ]
        }
    cursor = collection.find(
        query,
        {
            "_id": 0,
            "record_id": 1,
            "feature": 1,
            "label": 1,
            "category": 1,
            "saved_at": 1,
            "trade_date": 1,
            "run_id": 1,
            "path": 1,
            "ok": 1,
            "params": 1,
            "payload.result": 1,
        },
    ).sort([("saved_at", DESCENDING), ("feature", ASCENDING)]).limit(500)
    records = list(cursor)
    if compact:
        return [record for record in records if _record_matches_trade_date(record, compact)]
    return records


def _feature_card(record: dict[str, Any]) -> dict[str, Any]:
    feature = str(record.get("feature") or "")
    result = ((record.get("payload") or {}).get("result") if isinstance(record.get("payload"), dict) else None)
    rows = _result_rows(result)
    return {
        "feature": feature,
        "label": record.get("label") or KAIPANLA_FEATURES.get(feature, KaipanlaFeature(feature, feature, "", "", {})).label,
        "category": record.get("category") or KAIPANLA_FEATURES.get(feature, KaipanlaFeature(feature, feature, "", "", {})).category,
        "ok": bool(record.get("ok")),
        "saved_at": record.get("saved_at") or "",
        "run_id": record.get("run_id") or "",
        "path": record.get("path") or "",
        "item_count": _result_count(result, rows),
        "summary": _result_summary(result, rows),
        "rows": _slim_rows(rows, limit=8),
    }


def _overview_kpis(records: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    payloads = [((item.get("payload") or {}).get("result") if isinstance(item.get("payload"), dict) else None) for item in records.values()]
    candidates = [
        ("涨停", ["涨停", "zt", "limit_up"]),
        ("跌停", ["跌停", "dt", "limit_down"]),
        ("炸板", ["炸板", "broken", "open_board"]),
        ("最高连板", ["最高板", "最高连板", "height", "max_board"]),
        ("百日新高", ["百日新高", "new_high"]),
        ("大幅回撤", ["回撤", "withdrawal", "drawdown"]),
    ]
    items = []
    for label, keys in candidates:
        value = _overview_kpi_value(label, records, payloads, keys)
        items.append(
            {
                "label": label,
                "value": value if value is not None else "-",
                "status": "available" if value is not None else "missing",
                "hint": _overview_kpi_hint(label, value),
            }
        )
    return items


def _overview_kpi_hint(label: str, value: int | float | None) -> str:
    if value is None:
        if label in {"炸板", "最高连板"}:
            return "开盘啦当前记录未提供，待数据齐全后本地计算"
        return "从最新开盘啦记录自动识别"
    if label in {"炸板", "最高连板"}:
        return "开盘啦接口已返回或从明细识别"
    return "从最新开盘啦记录自动识别"


def _overview_kpi_value(label: str, records: dict[str, dict[str, Any]], payloads: list[Any], keys: list[str]) -> int | float | None:
    if label == "涨停":
        return _first_record_number(records, ["daily_data", "market_sentiment", "realtime_actual_limit_up_down"], ["涨停数", "涨停", "ZT", "limit_up_count", "actual_limit_up"])
    if label == "跌停":
        return _first_record_number(records, ["daily_data", "market_sentiment", "realtime_actual_limit_up_down"], ["跌停数", "跌停", "DT", "limit_down_count", "actual_limit_down"])
    if label == "炸板":
        direct = _first_record_number(records, ["daily_data", "market_sentiment"], ["炸板数", "炸板", "broken_limit_up", "open_board"])
        if direct is not None:
            return direct
        payload = _record_result(records.get("historical_broken_limit_up"))
        if payload is None:
            return None
        return _count_like_value(payload) or _result_count(payload, _result_rows(payload))
    if label == "最高连板":
        saw_explicit_zero = False
        for payload in (
            _record_result(records.get("consecutive_limit_up")),
            _record_result(records.get("market_limit_up_ladder")),
            _record_result(records.get("limit_up_ladder")),
        ):
            found = _find_number(payload, ["max_consecutive", "最高连板", "最高板", "height"])
            if found not in (None, 0):
                return found
            if found == 0:
                saw_explicit_zero = True
            derived = _max_consecutive_from_payload(payload)
            if derived not in (None, 0):
                return derived
            if derived == 0:
                saw_explicit_zero = True
        return 0 if saw_explicit_zero else None
    if label == "百日新高":
        payload = _record_result(records.get("new_high_data"))
        if payload is None:
            return None
        scalar = _to_number(payload)
        if scalar is not None:
            return scalar
        series_value = _series_latest_number(payload)
        if series_value is not None:
            return series_value
        found = _find_number(payload, ["new_high", "百日新高", "count", "total_count", "row_count"])
        return found if found is not None else _result_count(payload, _result_rows(payload))
    if label == "大幅回撤":
        payload = _record_result(records.get("sharp_withdrawal")) or _record_result(records.get("realtime_sharp_withdrawal"))
        if payload is None:
            return None
        count = _count_like_value(payload)
        if count is not None:
            return count
        found = _find_number(payload, ["withdrawal_num", "sharp_withdrawal", "count", "total_count", "row_count", "总数"])
        return found if found is not None else _result_count(payload, _result_rows(payload))
    return next((found for payload in payloads if (found := _find_number(payload, keys)) is not None), None)


def _first_record_number(records: dict[str, dict[str, Any]], features: list[str], keys: list[str]) -> int | float | None:
    for feature in features:
        found = _find_metric_number(_record_result(records.get(feature)), keys)
        if found is not None:
            return found
    return None


def _find_metric_number(value: Any, keys: list[str]) -> int | float | None:
    found = _find_number(value, keys)
    if found is not None:
        return found
    for row in _result_rows(value):
        metric = str(row.get("指标") or row.get("label") or row.get("name") or "")
        if not metric:
            continue
        if any(key.lower() in metric.lower() for key in keys):
            for value_key in ("值", "value", "count", "num"):
                number = _to_number(row.get(value_key))
                if number is not None:
                    return number
    return None


def _record_result(record: dict[str, Any] | None) -> Any:
    if not isinstance(record, dict):
        return None
    payload = record.get("payload")
    return payload.get("result") if isinstance(payload, dict) else None


def _series_latest_number(value: Any) -> int | float | None:
    if not isinstance(value, dict) or value.get("type") != "series":
        return None
    values = value.get("values")
    if not isinstance(values, list):
        return None
    for item in reversed(values):
        number = _to_number(item)
        if number is not None:
            return number
    return None


def _count_like_value(value: Any) -> int | float | None:
    if isinstance(value, dict):
        for key in ("count", "total_count", "row_count", "num", "总数"):
            number = _to_number(value.get(key))
            if number is not None:
                return number
        rows = _result_rows(value)
        if rows:
            for key in ("总数", "count", "total_count", "row_count", "num"):
                number = _to_number(rows[0].get(key))
                if number is not None:
                    return number
            return len(rows)
    if isinstance(value, list):
        return len(value)
    return _to_number(value)


def _max_consecutive_from_payload(value: Any) -> int | float | None:
    rows = _result_rows(value)
    numbers = [
        number
        for row in rows
        for key in ("连板天数", "连板数", "最高连板", "consecutive_days", "max_consecutive", "height", "board_num", "board")
        if (number := _to_number(row.get(key))) is not None
    ]
    ladder = value.get("ladder") if isinstance(value, dict) else None
    if isinstance(ladder, dict):
        for key, items in ladder.items():
            number = _to_number(key)
            if number is not None:
                numbers.append(number)
            if isinstance(items, list) and items:
                nested = _max_consecutive_from_payload(items)
                if nested is not None:
                    numbers.append(nested)
    return max(numbers) if numbers else None


def _overview_section(records: dict[str, dict[str, Any]], features: list[str]) -> list[dict[str, Any]]:
    return [_feature_card(records[key]) for key in features if key in records]


def _result_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        if value.get("type") == "series" and isinstance(value.get("index"), list) and isinstance(value.get("values"), list):
            return [
                {"指标": index, "值": item}
                for index, item in zip(value.get("index") or [], value.get("values") or [])
                if item not in (None, "")
            ]
        rows = value.get("rows")
        if isinstance(rows, list):
            return [item for item in rows if isinstance(item, dict)]
        for key in ("data", "items", "stocks", "list", "etfs"):
            rows = value.get(key)
            if isinstance(rows, list):
                return _result_row_list(rows, source_key=key)
        for item in value.values():
            nested = _result_rows(item)
            if nested:
                return nested
    if isinstance(value, list):
        return _result_row_list(value)
    return []


def _result_row_list(items: list[Any], *, source_key: str = "") -> list[dict[str, Any]]:
    rows = []
    for item in items:
        row = _result_row(item, source_key=source_key)
        if row:
            rows.append(row)
    return rows


def _result_row(item: Any, *, source_key: str = "") -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    if source_key == "etfs" and isinstance(item, (list, tuple)):
        return _etf_row(item)
    return {}


def _etf_row(item: list[Any] | tuple[Any, ...]) -> dict[str, Any]:
    keys = [
        "ETF代码",
        "ETF名称",
        "价格",
        "涨跌幅(%)",
        "成交额",
        "量比",
        "昨日增减金额",
        "昨日增减份额",
        "昨日增减比例(%)",
        "一周收益(%)",
        "一月收益(%)",
        "三个月收益(%)",
        "半年收益(%)",
        "总市值",
        "字段14",
        "字段15",
        "字段16",
        "字段17",
        "字段18",
        "今年以来(%)",
        "字段20",
    ]
    return {key: to_jsonable(item[index]) for index, key in enumerate(keys) if index < len(item)}


def _result_count(value: Any, rows: list[dict[str, Any]]) -> int:
    if rows:
        return len(rows)
    if isinstance(value, dict):
        for key in ("row_count", "total_count", "count", "total"):
            try:
                return int(value.get(key) or 0)
            except (TypeError, ValueError):
                pass
    if isinstance(value, list):
        return len(value)
    return 1 if value not in ({}, [], None) else 0


def _result_summary(value: Any, rows: list[dict[str, Any]]) -> str:
    if rows:
        keys = list(rows[0])[:3]
        return f"{len(rows)} 条 · " + " / ".join(str(rows[0].get(key, "")) for key in keys if rows[0].get(key) not in (None, ""))
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            if isinstance(item, (str, int, float, bool)) and len(parts) < 4:
                parts.append(f"{key}: {item}")
        return "；".join(parts) if parts else f"{len(value)} 个字段"
    if isinstance(value, list):
        return f"{len(value)} 条"
    return str(value)[:120] if value not in (None, "") else "无明细"


ROW_PRIORITY_KEYS = [
    "股票代码",
    "stock_code",
    "股票名称",
    "stock_name",
    "首次封板时间",
    "涨停时间",
    "timestamp",
    "连板天数",
    "consecutive_days",
    "board_type",
    "涨停原因",
    "limit_up_reason",
    "主题",
    "概念标签",
    "concepts",
    "总市值",
    "total_market_cap",
    "流通市值",
    "circulating_market_cap",
    "change_pct",
    "buy_amount",
    "ETF代码",
    "ETF名称",
    "价格",
    "涨跌幅(%)",
    "成交额",
    "量比",
    "一周收益(%)",
    "一月收益(%)",
    "今年以来(%)",
]


def _slim_rows(rows: list[dict[str, Any]], *, limit: int = 10) -> list[dict[str, Any]]:
    result = []
    for row in rows[:limit]:
        clean = {}
        ordered_keys = [key for key in ROW_PRIORITY_KEYS if key in row]
        ordered_keys.extend(key for key in row if key not in ordered_keys)
        for key in ordered_keys:
            value = row.get(key)
            if len(clean) >= limit:
                break
            if isinstance(value, (dict, list)):
                continue
            clean[str(key)] = to_jsonable(value)
        result.append(clean)
    return result


def _find_number(value: Any, needles: list[str]) -> int | float | None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key).lower()
            if any(needle.lower() in key_text for needle in needles):
                number = _to_number(item)
                if number is not None:
                    return number
            found = _find_number(item, needles)
            if found is not None:
                return found
    if isinstance(value, list):
        for item in value[:20]:
            found = _find_number(item, needles)
            if found is not None:
                return found
    return None


def _to_number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = value.replace(",", "").replace("%", "").strip()
        if re.fullmatch(r"-?\d+(?:\.\d+)?", text):
            number = float(text)
            return int(number) if number.is_integer() else number
    return None


def _record_trade_date(record: dict[str, Any]) -> str:
    trade_date = _normalize_date_text(record.get("trade_date"))
    if trade_date:
        return trade_date
    payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
    trade_date = _normalize_date_text(payload.get("trade_date"))
    if trade_date:
        return trade_date
    params = record.get("params") if isinstance(record.get("params"), dict) else {}
    for key in ("date", "end_date", "trade_date"):
        value = _normalize_date_text(params.get(key))
        if value:
            return value
    saved = str(record.get("saved_at") or "")
    return _normalize_date_text(saved[:8])


def _record_matches_trade_date(record: dict[str, Any], compact_date: str) -> bool:
    trade_date = _normalize_date_text(record.get("trade_date"))
    if trade_date:
        return trade_date == compact_date

    params = record.get("params") if isinstance(record.get("params"), dict) else {}
    exact_dates = [
        _normalize_date_text(params.get(key))
        for key in ("date", "trade_date")
        if params.get(key) not in (None, "")
    ]
    if exact_dates:
        return compact_date in exact_dates

    start_date = _normalize_date_text(params.get("start_date"))
    end_date = _normalize_date_text(params.get("end_date"))
    if start_date and end_date:
        return start_date <= compact_date <= end_date
    if end_date:
        return compact_date == end_date

    saved = _normalize_date_text(str(record.get("saved_at") or "")[:8])
    return saved == compact_date


def _params_with_trade_date(feature_key: str, params: dict[str, Any], trade_date: str) -> dict[str, Any]:
    feature = KAIPANLA_FEATURES[feature_key]
    merged = {**feature.default_params, **params}
    for key in ("date", "start_date", "end_date", "trade_date"):
        if key not in merged:
            continue
        value = _normalize_date_text(merged.get(key))
        if key == "start_date" or not value or value == _normalize_date_text(DEFAULT_DATE):
            merged[key] = trade_date
    if "num_days" in merged:
        merged["num_days"] = 1
    return merged


def _normalize_date_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 8:
        return digits[:8]
    return ""


def _display_date(value: str) -> str:
    digits = _normalize_date_text(value)
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}" if len(digits) == 8 else ""


def _filter_params(method, params: dict[str, Any]) -> dict[str, Any]:
    signature = inspect.signature(method)
    allowed = set(signature.parameters)
    return {key: value for key, value in params.items() if key in allowed}


def _kaipanla_collection(database: str = DEFAULT_DB):
    return _KaipanlaCollectionContext(database)


class _KaipanlaCollectionContext:
    def __init__(self, database: str):
        self.database = database
        self.client: MongoClient | None = None

    def __enter__(self):
        self.client = MongoClient(_mongo_uri(self.database), serverSelectionTimeoutMS=5000, socketTimeoutMS=8000)
        collection = self.client[self.database][KAIPANLA_COLLECTION]
        _ensure_kaipanla_indexes(collection)
        return collection

    def __exit__(self, *_args):
        if self.client:
            self.client.close()


def _ensure_kaipanla_indexes(collection: Any) -> None:
    collection.create_index([("record_id", ASCENDING)], unique=True)
    collection.create_index([("feature", ASCENDING), ("saved_at", DESCENDING)])
    collection.create_index([("run_id", ASCENDING)])
    collection.create_index([("path", ASCENDING)], sparse=True)


def _record_id(feature: str, saved_at: str, run_id: str) -> str:
    return f"{_safe_name(feature)}:{_safe_name(saved_at)}:{_safe_name(run_id)}"


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "run")).strip("_") or "run"
