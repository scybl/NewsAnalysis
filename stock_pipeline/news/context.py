from __future__ import annotations

from typing import Any

from .storage import Mysql, NewsDatabaseConfig, latest_news, search_news


def build_news_context(db_config: NewsDatabaseConfig, dossier: dict[str, Any], limit: int = 12) -> dict[str, Any]:
    terms = _company_terms(dossier)
    industry_terms = _industry_terms(dossier)
    with Mysql(db_config) as mysql:
        return {
            "company_news": search_news(mysql, terms, limit=limit, categories=["公司新闻"]) if terms else [],
            "industry_news": search_news(mysql, industry_terms, limit=limit, categories=["产经新闻", "金融市场", "区域经济"]) if industry_terms else [],
            "macro_news": latest_news(mysql, limit=limit, categories=["财经要闻", "宏观经济", "国际财经", "金融市场"]),
        }


def _company_terms(dossier: dict[str, Any]) -> list[str]:
    company = dossier.get("company", {})
    terms = []
    for source in (company.get("stock_basic", {}), company.get("stock_company", {})):
        for key in ("name", "fullname", "cnspell"):
            value = source.get(key)
            if value:
                terms.append(str(value))
    return _dedupe_terms(terms)


def _industry_terms(dossier: dict[str, Any]) -> list[str]:
    terms = []
    for row in dossier.get("industry", {}).get("sw_classification", []):
        for key in ("industry", "name", "l1_name", "l2_name", "l3_name"):
            value = row.get(key)
            if value:
                terms.append(str(value))
    return _dedupe_terms(terms)


def _dedupe_terms(terms: list[str]) -> list[str]:
    result = []
    seen = set()
    for term in terms:
        clean = term.strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result

