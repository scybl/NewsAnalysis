from __future__ import annotations

from pathlib import Path
from typing import Any

from .pinyin import pinyin_tokens
from .tushare_client import TushareClient
from .utils import ensure_dir, read_json, write_json


class StockSearchIndex:
    def __init__(self, client: TushareClient, cache_path: Path):
        self.client = client
        self.cache_path = cache_path
        self._stocks: list[dict[str, Any]] | None = None

    def stocks(self, refresh: bool = False) -> list[dict[str, Any]]:
        if self._stocks is not None and not refresh:
            return self._stocks
        if self.cache_path.exists() and not refresh:
            self._stocks = read_json(self.cache_path)
            return self._stocks

        rows = []
        for status in ("L", "P", "D"):
            result = self.client.query(
                "stock_basic",
                {"list_status": status},
                "ts_code,symbol,name,area,industry,market,list_date,exchange,list_status",
            )
            rows.extend(result.records)
        seen = set()
        enriched = []
        for row in rows:
            ts_code = row.get("ts_code")
            if not ts_code or ts_code in seen:
                continue
            seen.add(ts_code)
            name = str(row.get("name") or "")
            full_pinyin, initials = pinyin_tokens(name)
            enriched.append({**row, "pinyin": full_pinyin, "initials": initials})
        enriched.sort(key=lambda item: (item.get("list_status") != "L", item.get("symbol") or ""))
        ensure_dir(self.cache_path.parent)
        write_json(self.cache_path, enriched)
        self._stocks = enriched
        return enriched

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        q = query.strip().lower().replace(" ", "")
        if not q:
            return []
        results = []
        for row in self.stocks():
            symbol = str(row.get("symbol") or "").lower()
            ts_code = str(row.get("ts_code") or "").lower()
            name = str(row.get("name") or "").lower()
            pinyin = str(row.get("pinyin") or "").lower()
            initials = str(row.get("initials") or "").lower()
            score = _score(q, symbol, ts_code, name, pinyin, initials)
            if score is not None:
                results.append((score, row))
        results.sort(key=lambda item: (item[0], item[1].get("list_status") != "L", item[1].get("symbol") or ""))
        return [item[1] for item in results[:limit]]


def _score(q: str, symbol: str, ts_code: str, name: str, pinyin: str, initials: str) -> int | None:
    if q == symbol or q == ts_code:
        return 0
    if symbol.startswith(q) or ts_code.startswith(q):
        return 1
    if q == name:
        return 2
    if name.startswith(q):
        return 3
    if q == initials:
        return 4
    if initials.startswith(q):
        return 5
    if q == pinyin:
        return 6
    if pinyin.startswith(q):
        return 7
    if q in name:
        return 8
    if q in pinyin or q in initials:
        return 9
    return None
