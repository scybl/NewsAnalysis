from __future__ import annotations

import math
from pathlib import Path
from statistics import mean
from typing import Any

from .config import PROJECT_ROOT
from .utils import ensure_dir, read_json, sorted_records, write_json


CORE_FEATURES = (
    "return_20d",
    "return_60d",
    "max_drawdown_60d",
    "volume_ratio_5d_vs_20d",
    "turnover_percentile_120d",
    "pb_percentile_3y",
    "moneyflow_20d_vs_circ_mv",
)


def build_similarity_learning(
    full_data: dict[str, Any],
    analysis_type: str,
    *,
    library_root: Path | None = None,
    top_n: int = 10,
) -> dict[str, Any]:
    """Build Phase 1 historical similarity context from local datasets only."""
    datasets = full_data.get("datasets", {})
    daily = _ascending_records(datasets.get("daily", []), "trade_date")
    daily_basic = _records_by_date(datasets.get("daily_basic", []), "trade_date")
    moneyflow = _records_by_date(datasets.get("moneyflow", []), "trade_date")
    regime_rows = _ascending_records(datasets.get("sw_daily", []) or datasets.get("daily", []), "trade_date")

    feature_rows = build_daily_pattern_features(daily, daily_basic, moneyflow)
    current = feature_rows[-1] if feature_rows else {}
    market_regime = _market_regime(regime_rows)
    cases = find_similar_windows(current, feature_rows, top_n=top_n)
    distribution = estimate_outcome_distribution(cases)
    failure_matches = match_failure_cases(
        current,
        distribution,
        market_regime,
        analysis_type,
        library_root=library_root,
    )

    warnings = []
    if not current:
        warnings.append("本地日线数据不足，无法构建相似走势特征。")
    if len(cases) < max(3, min(top_n, 5)):
        warnings.append("可用历史相似样本偏少，结局概率只能作为案例提示。")
    if distribution.get("uncertainty_level") == "high":
        warnings.append("三类结局概率接近，不能压缩为单一标签。")
    if failure_matches:
        warnings.append("当前结构命中过去系统判断错误案例，需要降低结论置信度。")

    return {
        "version": "phase1_euclidean_v1",
        "ts_code": full_data.get("ts_code"),
        "analysis_type": analysis_type,
        "market_regime": market_regime,
        "query_features": _feature_view(current),
        "core_features": list(CORE_FEATURES),
        "similar_cases": cases,
        "outcome_distribution": distribution,
        "failure_case_matches": failure_matches,
        "warnings": warnings,
        "notes": [
            "Phase 1 只使用本地 daily/daily_basic/moneyflow 和加权欧氏距离。",
            "输出为概率分布和案例证据，不提供确定性预测。",
        ],
        "data_quality": {
            "daily_rows": len(daily),
            "feature_rows": len(feature_rows),
            "similar_case_count": len(cases),
            "failure_case_count": len(_load_failure_cases(library_root)),
        },
    }


def build_daily_pattern_features(
    daily: list[dict[str, Any]],
    daily_basic_by_date: dict[str, dict[str, Any]],
    moneyflow_by_date: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    closes = [_num(row.get("close")) for row in daily]
    vols = [_num(row.get("vol")) for row in daily]
    dates = [str(row.get("trade_date") or "") for row in daily]

    for index, row in enumerate(daily):
        if index < 120:
            continue
        date = dates[index]
        close = closes[index]
        if close is None or not date:
            continue
        basic = daily_basic_by_date.get(date, {})
        feature_row = {
            "trade_date": date,
            "close": close,
            "return_20d": _return_pct(closes, index, 20),
            "return_60d": _return_pct(closes, index, 60),
            "max_drawdown_60d": _max_drawdown_pct([value for value in closes[index - 59 : index + 1] if value is not None]),
            "volume_ratio_5d_vs_20d": _avg_ratio(vols[index - 4 : index + 1], vols[index - 19 : index + 1]),
            "turnover_percentile_120d": _percentile_rank(_num(basic.get("turnover_rate")), _basic_window(daily_basic_by_date, dates, index, "turnover_rate", 120)),
            "pb_percentile_3y": _percentile_rank(_num(basic.get("pb")), _basic_window(daily_basic_by_date, dates, index, "pb", 750)),
            "moneyflow_20d_vs_circ_mv": _moneyflow_ratio(moneyflow_by_date, dates, index, _num(basic.get("circ_mv"))),
            "forward_return_20d": _forward_return_pct(closes, index, 20),
            "forward_return_60d": _forward_return_pct(closes, index, 60),
            "forward_return_120d": _forward_return_pct(closes, index, 120),
            "forward_max_drawdown_20d": _forward_max_drawdown_pct(closes, index, 20),
            "forward_max_drawdown_60d": _forward_max_drawdown_pct(closes, index, 60),
            "forward_max_drawdown_120d": _forward_max_drawdown_pct(closes, index, 120),
        }
        rows.append(feature_row)
    return rows


def find_similar_windows(
    current: dict[str, Any],
    feature_rows: list[dict[str, Any]],
    *,
    top_n: int = 10,
) -> list[dict[str, Any]]:
    if not current or not feature_rows:
        return []
    candidates = [
        row
        for row in feature_rows
        if row.get("trade_date") != current.get("trade_date") and row.get("forward_return_20d") is not None
    ]
    stats = _feature_stats(candidates, current)
    scored = []
    for row in candidates:
        distance, used = _distance(current, row, stats)
        if distance is None:
            continue
        outcome = classify_case_outcome(row)
        scored.append(
            {
                "trade_date": row.get("trade_date"),
                "similarity": round(max(0.0, 1.0 / (1.0 + distance)), 4),
                "distance": round(distance, 4),
                "used_features": used,
                "feature_snapshot": _feature_view(row),
                "forward_returns": {
                    "20d": _round(row.get("forward_return_20d")),
                    "60d": _round(row.get("forward_return_60d")),
                    "120d": _round(row.get("forward_return_120d")),
                },
                "forward_max_drawdown": {
                    "20d": _round(row.get("forward_max_drawdown_20d")),
                    "60d": _round(row.get("forward_max_drawdown_60d")),
                    "120d": _round(row.get("forward_max_drawdown_120d")),
                },
                "outcome_class": outcome,
            }
        )
    return sorted(scored, key=lambda item: item["distance"])[:top_n]


def estimate_outcome_distribution(cases: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"value_repair": 0, "value_trap": 0, "long_flat": 0}
    for case in cases:
        label = case.get("outcome_class")
        if label in counts:
            counts[label] += 1
    total = sum(counts.values())
    if not total:
        distribution = {key: 0 for key in counts}
    else:
        raw = {key: counts[key] * 100 / total for key in counts}
        distribution = _rounded_distribution(raw)
    values = sorted(distribution.values(), reverse=True)
    gap = values[0] - values[1] if len(values) >= 2 else 100
    return {
        "sample_size": total,
        "distribution": distribution,
        "uncertainty_level": "high" if total < 5 or gap < 15 else "medium",
        "top_outcome": max(distribution.items(), key=lambda item: item[1])[0] if total else "",
        "interpretation": _distribution_interpretation(distribution, total, gap),
    }


def classify_case_outcome(row: dict[str, Any]) -> str:
    ret20 = _num(row.get("forward_return_20d"))
    ret60 = _num(row.get("forward_return_60d"))
    ret120 = _num(row.get("forward_return_120d"))
    drawdown60 = _num(row.get("forward_max_drawdown_60d"))
    drawdown120 = _num(row.get("forward_max_drawdown_120d"))
    if (ret20 is not None and ret20 >= 12) or (ret60 is not None and ret60 >= 20) or (ret120 is not None and ret120 >= 28):
        return "value_repair"
    if (ret60 is not None and ret60 <= -25) or (ret120 is not None and ret120 <= -35):
        return "value_trap"
    if (drawdown60 is not None and drawdown60 <= -30) or (drawdown120 is not None and drawdown120 <= -40):
        return "value_trap"
    return "long_flat"


def match_failure_cases(
    current: dict[str, Any],
    distribution: dict[str, Any],
    market_regime: dict[str, Any],
    analysis_type: str,
    *,
    library_root: Path | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    cases = _load_failure_cases(library_root)
    if not cases or not current:
        return []
    stats = _feature_stats([case.get("feature_snapshot", {}) for case in cases if isinstance(case.get("feature_snapshot"), dict)], current)
    matches = []
    current_dist = distribution.get("distribution", {})
    for case in cases:
        score_parts = []
        feature_snapshot = case.get("feature_snapshot")
        if isinstance(feature_snapshot, dict):
            distance, used = _distance(current, feature_snapshot, stats)
            if distance is not None:
                score_parts.append(max(0.0, 1.0 / (1.0 + distance)))
            else:
                used = []
        else:
            used = []
        if case.get("analysis_type") == analysis_type:
            score_parts.append(0.18)
        case_regime = case.get("market_regime", {})
        if isinstance(case_regime, dict) and case_regime.get("trend") == market_regime.get("trend"):
            score_parts.append(0.14)
        predicted = case.get("predicted_distribution", {})
        if isinstance(predicted, dict) and current_dist:
            score_parts.append(_distribution_similarity(current_dist, predicted) * 0.28)
        similarity = round(sum(score_parts), 4)
        if similarity <= 0:
            continue
        matches.append(
            {
                "case_id": case.get("case_id") or case.get("id") or "",
                "ts_code": case.get("ts_code", ""),
                "analysis_date": case.get("analysis_date", ""),
                "analysis_type": case.get("analysis_type", ""),
                "failure_type": case.get("failure_type", ""),
                "failure_similarity": similarity,
                "used_features": used,
                "actual_outcome": case.get("actual_outcome", {}),
                "postmortem": case.get("postmortem", {}),
            }
        )
    return sorted(matches, key=lambda item: item["failure_similarity"], reverse=True)[:limit]


def ensure_failure_case_library(root: Path | None = None) -> Path:
    library = root or PROJECT_ROOT / "local_data" / "failure_case_library"
    ensure_dir(library)
    cases_path = library / "cases.json"
    if not cases_path.exists():
        write_json(cases_path, [])
    readme_path = library / "README.md"
    if not readme_path.exists():
        readme_path.write_text(
            "# Failure Case Library\n\n"
            "手工登记系统被事后结果推翻的案例。第一版读取 cases.json，也会读取 cases/*.json。\n",
            encoding="utf-8",
        )
    return library


def _load_failure_cases(root: Path | None = None) -> list[dict[str, Any]]:
    library = ensure_failure_case_library(root)
    cases: list[dict[str, Any]] = []
    cases_path = library / "cases.json"
    try:
        value = read_json(cases_path)
        if isinstance(value, list):
            cases.extend(item for item in value if isinstance(item, dict))
    except Exception:
        pass
    cases_dir = library / "cases"
    if cases_dir.exists():
        for path in sorted(cases_dir.glob("*.json")):
            try:
                value = read_json(path)
            except Exception:
                continue
            if isinstance(value, dict):
                cases.append(value)
    return cases


def _market_regime(rows: list[dict[str, Any]]) -> dict[str, Any]:
    closes = [_num(row.get("close")) for row in rows if _num(row.get("close")) is not None]
    if len(closes) < 120:
        return {"trend": "unknown", "liquidity": "unknown", "style": "unknown", "risk_appetite": "unknown", "evidence": ["市场/行业历史数据不足，Phase 1 无法判断 regime。"]}
    latest = closes[-1]
    close_60 = closes[-61]
    ma120 = mean(closes[-120:])
    ret60 = (latest / close_60 - 1) * 100 if close_60 else 0
    if ret60 >= 8 and latest >= ma120:
        trend = "bull"
    elif ret60 <= -8 and latest < ma120:
        trend = "bear"
    else:
        trend = "range"
    volumes = [_num(row.get("amount") or row.get("vol")) for row in rows if _num(row.get("amount") or row.get("vol")) is not None]
    liquidity = "unknown"
    if len(volumes) >= 60 and mean(volumes[-60:-20] or volumes[-60:]):
        ratio = mean(volumes[-20:]) / mean(volumes[-60:-20] or volumes[-60:])
        liquidity = "loose" if ratio >= 1.2 else "tight" if ratio <= 0.8 else "neutral"
    return {
        "trend": trend,
        "liquidity": liquidity,
        "style": "unknown",
        "risk_appetite": "medium" if trend == "range" else "high" if trend == "bull" else "low",
        "evidence": [
            f"Phase 1 使用本地行业/个股代理数据判断，60日收益 {round(ret60, 2)}%。",
            f"最新收盘 {'高于' if latest >= ma120 else '低于'} 120日均线。",
        ],
    }


def _ascending_records(records: list[dict[str, Any]], date_field: str) -> list[dict[str, Any]]:
    return list(reversed(sorted_records(records, (date_field,))))


def _records_by_date(records: list[dict[str, Any]], date_field: str) -> dict[str, dict[str, Any]]:
    return {str(row.get(date_field)): row for row in records if row.get(date_field)}


def _return_pct(values: list[float | None], index: int, window: int) -> float | None:
    if index < window:
        return None
    current = values[index]
    previous = values[index - window]
    if current is None or previous in (None, 0):
        return None
    return round((current / previous - 1) * 100, 4)


def _forward_return_pct(values: list[float | None], index: int, window: int) -> float | None:
    if index + window >= len(values):
        return None
    current = values[index]
    future = values[index + window]
    if current in (None, 0) or future is None:
        return None
    return round((future / current - 1) * 100, 4)


def _max_drawdown_pct(values: list[float]) -> float | None:
    if not values:
        return None
    peak = values[0]
    drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        if peak:
            drawdown = min(drawdown, value / peak - 1)
    return round(drawdown * 100, 4)


def _forward_max_drawdown_pct(values: list[float | None], index: int, window: int) -> float | None:
    if index + 1 >= len(values):
        return None
    selected = [value for value in values[index : min(len(values), index + window + 1)] if value is not None]
    if not selected:
        return None
    start = selected[0]
    if not start:
        return None
    return round((min(selected) / start - 1) * 100, 4)


def _avg_ratio(numerator_values: list[float | None], denominator_values: list[float | None]) -> float | None:
    numerator = [value for value in numerator_values if value is not None]
    denominator = [value for value in denominator_values if value is not None]
    if not numerator or not denominator:
        return None
    base = mean(denominator)
    if not base:
        return None
    return round(mean(numerator) / base, 4)


def _basic_window(daily_basic_by_date: dict[str, dict[str, Any]], dates: list[str], index: int, field: str, window: int) -> list[float]:
    values = []
    start = max(0, index - window + 1)
    for date in dates[start : index + 1]:
        value = _num(daily_basic_by_date.get(date, {}).get(field))
        if value is not None:
            values.append(value)
    return values


def _percentile_rank(value: float | None, samples: list[float]) -> float | None:
    if value is None or not samples:
        return None
    below = sum(1 for item in samples if item <= value)
    return round(below / len(samples) * 100, 4)


def _moneyflow_ratio(moneyflow_by_date: dict[str, dict[str, Any]], dates: list[str], index: int, circ_mv: float | None) -> float | None:
    if not circ_mv:
        return None
    total = 0.0
    found = 0
    for date in dates[max(0, index - 19) : index + 1]:
        value = _money_net(moneyflow_by_date.get(date, {}))
        if value is None:
            continue
        total += value
        found += 1
    if not found:
        return None
    return round(total / circ_mv * 100, 4)


def _money_net(row: dict[str, Any]) -> float | None:
    explicit = _num(row.get("net_mf_amount"))
    if explicit is not None:
        return explicit
    buy = sum(_num(row.get(key)) or 0 for key in ("buy_sm_amount", "buy_md_amount", "buy_lg_amount", "buy_elg_amount"))
    sell = sum(_num(row.get(key)) or 0 for key in ("sell_sm_amount", "sell_md_amount", "sell_lg_amount", "sell_elg_amount"))
    if not buy and not sell:
        return None
    return buy - sell


def _feature_stats(candidates: list[dict[str, Any]], current: dict[str, Any]) -> dict[str, tuple[float, float]]:
    stats: dict[str, tuple[float, float]] = {}
    for key in CORE_FEATURES:
        values = [_num(row.get(key)) for row in candidates]
        current_value = _num(current.get(key))
        cleaned = [value for value in values if value is not None]
        if current_value is not None:
            cleaned.append(current_value)
        if len(cleaned) < 2:
            continue
        avg = mean(cleaned)
        variance = sum((value - avg) ** 2 for value in cleaned) / len(cleaned)
        std = math.sqrt(variance) or 1.0
        stats[key] = (avg, std)
    return stats


def _distance(current: dict[str, Any], candidate: dict[str, Any], stats: dict[str, tuple[float, float]]) -> tuple[float | None, list[str]]:
    parts = []
    used = []
    for key in CORE_FEATURES:
        current_value = _num(current.get(key))
        candidate_value = _num(candidate.get(key))
        if current_value is None or candidate_value is None or key not in stats:
            continue
        avg, std = stats[key]
        parts.append(((current_value - avg) / std - (candidate_value - avg) / std) ** 2)
        used.append(key)
    if len(parts) < 4:
        return None, used
    return math.sqrt(sum(parts) / len(parts)), used


def _feature_view(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _round(row.get(key)) for key in CORE_FEATURES if row.get(key) is not None}


def _distribution_similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    keys = ("value_repair", "value_trap", "long_flat")
    distance = sum(abs((_num(a.get(key)) or 0) - (_num(b.get(key)) or 0)) for key in keys)
    return max(0.0, 1.0 - distance / 200)


def _rounded_distribution(raw: dict[str, float]) -> dict[str, int]:
    rounded = {key: int(round(value)) for key, value in raw.items()}
    diff = 100 - sum(rounded.values())
    if diff:
        key = max(raw.items(), key=lambda item: item[1] - int(item[1]))[0]
        rounded[key] += diff
    return rounded


def _distribution_interpretation(distribution: dict[str, int], total: int, gap: int | float) -> str:
    if not total:
        return "样本不足，无法形成结局概率。"
    leader, leader_value = max(distribution.items(), key=lambda item: item[1])
    label = {"value_repair": "价值修复", "value_trap": "价值陷阱", "long_flat": "长期横盘"}.get(leader, leader)
    if gap < 15:
        return f"{label}概率略占优，但三类结局接近，不确定性高。"
    return f"{label}概率最高，但仍需结合市场状态和反证复核。"


def _num(value: Any) -> float | None:
    try:
        if value in ("", None):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: Any, digits: int = 4) -> float | None:
    number = _num(value)
    if number is None:
        return None
    return round(number, digits)
