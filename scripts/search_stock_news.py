#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from stock_pipeline.news_search import search_related_news  # noqa: E402
from stock_pipeline.stock_storage import current_dir, stock_exists  # noqa: E402
from stock_pipeline.utils import normalize_ts_code, read_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="从 MongoDB 新闻库检索某只股票的相关新闻线索。")
    parser.add_argument("code", help="股票代码，例如 002714 或 002714.SZ")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--days", type=int, default=60)
    args = parser.parse_args()

    ts_code = normalize_ts_code(args.code)
    if not stock_exists(ts_code):
        raise SystemExit(f"本地还没有 {ts_code} 的 Tushare 资料包，请先更新股票数据。")

    base_dir = current_dir(ts_code)
    full_data = read_json(base_dir / "full_data.json")
    dossier = read_json(base_dir / "dossier.json")
    company = _company_identity(dossier, full_data)
    result = search_related_news(company, limit=args.limit, days=args.days)
    print(json.dumps({"ts_code": ts_code, **result}, ensure_ascii=False, indent=2))
    return 0


def _company_identity(dossier: dict, full_data: dict) -> dict:
    company = dossier.get("company", {})
    stock_basic = company.get("stock_basic") or {}
    stock_company = company.get("stock_company") or {}
    industry_rows = dossier.get("industry", {}).get("sw_classification") or full_data.get("datasets", {}).get("index_member_all", [])
    industry = ""
    if industry_rows and isinstance(industry_rows, list):
        first = industry_rows[0]
        industry = str(first.get("industry_name") or first.get("index_name") or first.get("l2_name") or first.get("l1_name") or "")
    ts_code = stock_basic.get("ts_code") or full_data.get("ts_code")
    return {
        "ts_code": ts_code,
        "symbol": stock_basic.get("symbol") or str(ts_code or "").split(".")[0],
        "name": stock_basic.get("name") or stock_company.get("name") or stock_company.get("com_name"),
        "industry": stock_basic.get("industry") or industry,
        "area": stock_basic.get("area") or stock_company.get("province"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
