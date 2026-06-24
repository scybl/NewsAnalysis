from __future__ import annotations

import inspect
import json
import re
from dataclasses import dataclass, asdict
from datetime import date
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT
from .kaipanla_crawler import KaipanlaCrawler
from .utils import ensure_dir, read_json, timestamp, write_json


DEFAULT_DATE = "2026-01-16"
KAIPANLA_DATA_DIR = PROJECT_ROOT / "local_data" / "kaipanla"


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
    "longhubang_stock_list": KaipanlaFeature("longhubang_stock_list", "龙虎榜列表", "龙虎榜", "指定日期龙虎榜股票列表。", {"date": DEFAULT_DATE, "index": 0, "page_size": 100, "timeout": 20}),
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


def run_kaipanla_feature(key: str, params: dict[str, Any] | None = None, *, save: bool = False, run_id: str = "") -> dict[str, Any]:
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
    if save:
        payload["saved"] = save_kaipanla_result(key, payload, run_id=run_id)
    return payload


def run_kaipanla_batch(feature_keys: list[str], params_by_feature: dict[str, dict[str, Any]] | None = None, *, save: bool = True, run_id: str = "") -> dict[str, Any]:
    selected = [key for key in feature_keys if key in KAIPANLA_FEATURES]
    if not selected:
        raise ValueError("请至少选择一个开盘啦功能。")
    results = []
    succeeded = 0
    failed = 0
    for key in selected:
        try:
            result = run_kaipanla_feature(key, (params_by_feature or {}).get(key) or {}, save=save, run_id=run_id)
            results.append({"feature": key, "ok": True, "saved": result.get("saved", {})})
            succeeded += 1
        except Exception as exc:  # noqa: BLE001 - batch should keep remaining features running
            results.append({"feature": key, "ok": False, "error": str(exc)})
            failed += 1
    return {
        "ok": failed == 0,
        "run_id": run_id,
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
    feature_dir = ensure_dir(KAIPANLA_DATA_DIR / key)
    filename = f"{saved_at}_{clean_run_id}.json"
    path = feature_dir / filename
    record = {
        "schema": "kaipanla.result.v1",
        "feature": key,
        "label": KAIPANLA_FEATURES[key].label,
        "category": KAIPANLA_FEATURES[key].category,
        "saved_at": saved_at,
        "run_id": run_id or clean_run_id,
        "payload": payload,
    }
    write_json(path, record)
    _append_kaipanla_index(
        {
            "feature": key,
            "label": KAIPANLA_FEATURES[key].label,
            "category": KAIPANLA_FEATURES[key].category,
            "saved_at": saved_at,
            "run_id": run_id or clean_run_id,
            "path": str(path),
            "ok": bool(payload.get("ok")),
            "params": payload.get("params", {}),
        }
    )
    return {"path": str(path), "saved_at": saved_at, "run_id": run_id or clean_run_id}


def list_kaipanla_records(limit: int = 80, feature: str = "") -> dict[str, Any]:
    index_path = KAIPANLA_DATA_DIR / "index.json"
    payload = read_json(index_path) if index_path.exists() else {"items": []}
    items = payload.get("items", []) if isinstance(payload, dict) else []
    if feature:
        items = [item for item in items if item.get("feature") == feature]
    items = sorted(items, key=lambda item: item.get("saved_at", ""), reverse=True)[: max(1, min(500, limit))]
    return {"items": items, "count": len(items), "data_dir": str(KAIPANLA_DATA_DIR)}


def read_kaipanla_record(path: str) -> dict[str, Any]:
    target = Path(path)
    root = KAIPANLA_DATA_DIR.resolve()
    resolved = target.resolve()
    if root not in resolved.parents and resolved != root:
        raise ValueError("只能读取开盘啦本地数据目录内的记录。")
    return read_json(resolved)


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


def _filter_params(method, params: dict[str, Any]) -> dict[str, Any]:
    signature = inspect.signature(method)
    allowed = set(signature.parameters)
    return {key: value for key, value in params.items() if key in allowed}


def _append_kaipanla_index(item: dict[str, Any]) -> None:
    ensure_dir(KAIPANLA_DATA_DIR)
    index_path = KAIPANLA_DATA_DIR / "index.json"
    payload = read_json(index_path) if index_path.exists() else {"version": 1, "items": []}
    items = payload.get("items", []) if isinstance(payload, dict) else []
    items.insert(0, item)
    write_json(index_path, {"version": 1, "items": items[:1000]})


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "run")).strip("_") or "run"
