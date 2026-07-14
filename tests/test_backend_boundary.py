from pathlib import Path

from backend.auth_policy import ADMIN_ONLY_PAGES, DATA_CONSOLE_PAGES
from backend.fetch_registry import DATA_FETCH_ACTIONS, DATA_KEYS, FETCH_METHODS, SPIDER_SOURCES, data_key_snapshot, fetch_method_snapshot
from backend.paths import STATIC_DIR


ROOT = Path(__file__).resolve().parents[1]


def test_backend_static_dir_points_to_frontend_admin():
    assert STATIC_DIR == ROOT / "frontend" / "admin"
    assert (STATIC_DIR / "admin.js").exists()


def test_backend_page_policy_keeps_data_console_and_admin_pages_separate():
    assert DATA_CONSOLE_PAGES == {"/admin-market.html", "/admin-news.html", "/admin-crawler.html"}
    assert "/admin-accounts.html" in ADMIN_ONLY_PAGES
    assert DATA_CONSOLE_PAGES.isdisjoint(ADMIN_ONLY_PAGES)


def test_backend_fetch_registry_uses_canonical_data_keys():
    assert DATA_KEYS["stock.daily_k"].temperature == "hot"
    assert DATA_KEYS["stock.minute"].temperature == "cold"
    assert DATA_KEYS["news.raw_article"].owner == "newscrawler"
    assert FETCH_METHODS["stock.package.sync"].default_provider == "akshare"
    assert FETCH_METHODS["stock.package.sync"].data_key == "stock.package"
    assert "AkShare" in DATA_FETCH_ACTIONS["/api/sync-stock-data"]
    assert "Tushare" in FETCH_METHODS["stock.package.sync"].notes


def test_backend_spider_sources_reference_fetch_registry():
    source = SPIDER_SOURCES[0]

    assert source["id"] == "ths_market"
    assert source["data_key"] in DATA_KEYS
    assert source["fetch_method"] in FETCH_METHODS


def test_web_exposes_backend_registry_endpoint_contract():
    web = (ROOT / "stock_pipeline" / "web.py").read_text(encoding="utf-8")

    assert 'parsed.path == "/api/admin/backend/registry"' in web
    assert '"data_keys": data_key_snapshot()' in web
    assert '"fetch_methods": fetch_method_snapshot()' in web
    assert data_key_snapshot()[0]["key"] in DATA_KEYS
    assert fetch_method_snapshot()[0]["key"] in FETCH_METHODS
