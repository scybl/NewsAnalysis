from news_crawler.config import get_settings


def test_bloomberg_runtime_config_can_be_loaded_from_files(monkeypatch, tmp_path):
    latest = tmp_path / "latest.txt"
    api = tmp_path / "api.txt"
    use_api = tmp_path / "use_api.txt"
    cookies = tmp_path / "cookies.txt"
    require_login = tmp_path / "require_login.txt"
    latest.write_text("https://www.bloomberg.com/latest", encoding="utf-8")
    api.write_text("https://www.bloomberg.com/lineup-next/api/stories", encoding="utf-8")
    use_api.write_text("0", encoding="utf-8")
    cookies.write_text('[{"domain":".bloomberg.com","name":"_breg-uid","value":"abc"}]', encoding="utf-8")
    require_login.write_text("1", encoding="utf-8")

    for name in ("BLOOMBERG_LATEST_URL", "BLOOMBERG_API_URL", "BLOOMBERG_USE_API", "BLOOMBERG_COOKIES_JSON", "BLOOMBERG_REQUIRE_LOGIN_COOKIE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BLOOMBERG_LATEST_URL_FILE", str(latest))
    monkeypatch.setenv("BLOOMBERG_API_URL_FILE", str(api))
    monkeypatch.setenv("BLOOMBERG_USE_API_FILE", str(use_api))
    monkeypatch.setenv("BLOOMBERG_COOKIES_JSON_FILE", str(cookies))
    monkeypatch.setenv("BLOOMBERG_REQUIRE_LOGIN_COOKIE_FILE", str(require_login))

    settings = get_settings()

    assert settings.bloomberg_latest_url == "https://www.bloomberg.com/latest"
    assert settings.bloomberg_api_url == "https://www.bloomberg.com/lineup-next/api/stories"
    assert settings.bloomberg_use_api is False
    assert settings.bloomberg_cookies_json == '[{"domain":".bloomberg.com","name":"_breg-uid","value":"abc"}]'
    assert settings.bloomberg_require_login_cookie is True


def test_default_disabled_sources_pause_politico_web(monkeypatch):
    monkeypatch.delenv("NEWS_CRAWLER_DISABLED_SOURCES", raising=False)

    settings = get_settings()

    assert settings.politico_browser_news_url == "https://www.politico.com/"
    assert settings.disabled_sources == frozenset({"bloomberg", "politico_browser", "politico_rss", "politico_chrome"})
