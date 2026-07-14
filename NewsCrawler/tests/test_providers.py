import json
from pathlib import Path

import requests

from news_crawler.models import NewsCrawlRequest
from news_crawler.models import ArticleRef
from news_crawler.providers.bloomberg import BloombergCredentialExpired, BloombergProvider, extract_bloomberg_api_urls, extract_bloomberg_urls, parse_bloomberg_article, parse_browser_cookies as parse_bloomberg_cookies, validate_bloomberg_login_cookies
from news_crawler.providers.guardian import GuardianProvider
from news_crawler.providers.politico import DEFAULT_FEEDS as POLITICO_DEFAULT_FEEDS
from news_crawler.providers.politico import PoliticoProvider, parse_politico_feed
from news_crawler.providers.politico_browser import PoliticoBrowserProvider, extract_politico_news_urls, parse_browser_cookies
from news_crawler.providers.tonghuashun import DEFAULT_CATEGORY_HARD_LIMITS, TonghuashunProvider, _image_urls, _normalize_ocr_text, _usable_ocr_text
from news_crawler.providers.tonghuashun import _mobile_url


FIXTURES = Path(__file__).parent / "fixtures"


class Response:
    def __init__(self, *, text="", payload=None, url="https://example.com", status_code=200):
        self.text = text
        self.content = text.encode()
        self.encoding = "utf-8"
        self.url = url
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class QueueSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.headers = {}

    def get(self, *_args, **_kwargs):
        return next(self.responses)


class RecordingQueueSession(QueueSession):
    def __init__(self, responses):
        super().__init__(responses)
        self.requests = []

    def get(self, url, **kwargs):
        self.requests.append({"url": url, **kwargs})
        return super().get(url, **kwargs)


class FailingSession:
    def __init__(self, exc):
        self.exc = exc
        self.headers = {}

    def get(self, *_args, **_kwargs):
        raise self.exc


class RecordingSession:
    def __init__(self, response):
        self.response = response
        self.headers = {}
        self.urls = []

    def get(self, url, **_kwargs):
        self.urls.append(url)
        return self.response


class FakeBrowser:
    def __init__(self, pages):
        self.pages = dict(pages)
        self.current_url = ""
        self.page_source = ""
        self.closed = False
        self.scripts = []
        self.cookies = []

    def get(self, url):
        self.current_url = url
        self.page_source = self.pages[url]

    def execute_script(self, script):
        self.scripts.append(script)

    def add_cookie(self, cookie):
        self.cookies.append(cookie)

    def quit(self):
        self.closed = True


def test_tonghuashun_provider_parses_fixture():
    list_html = (FIXTURES / "tonghuashun_list.html").read_text()
    article_html = (FIXTURES / "tonghuashun_article.html").read_text()
    provider = TonghuashunProvider()
    provider.session = QueueSession([
        Response(text=list_html),
        Response(text=article_html, url="http://m.10jqka.com.cn/20260625/c123456.shtml"),
    ])
    ref = next(iter(provider.discover(NewsCrawlRequest(categories=("财经要闻",), max_pages=1))))
    article = provider.fetch(ref)
    assert article.external_id == "123456"
    assert article.title == "示例财经新闻"
    assert article.published_at.utcoffset().total_seconds() == 8 * 3600


def test_tonghuashun_uses_category_page_overrides_as_hard_limits():
    list_html = (FIXTURES / "tonghuashun_list.html").read_text()
    provider = TonghuashunProvider()
    session = RecordingSession(Response(text=list_html))
    provider.session = session

    refs = list(provider.discover(NewsCrawlRequest(
        categories=("财经要闻", "产经新闻"),
        max_pages=1,
        category_pages={"财经要闻": 2, "产经新闻": 1},
    )))

    assert [ref.section for ref in refs] == ["财经要闻", "财经要闻", "产经新闻"]
    assert [ref.metadata["crawl_hard_limit"] for ref in refs] == [2, 2, 1]
    assert session.urls == [
        "http://news.10jqka.com.cn/today_list/index_1.shtml",
        "http://news.10jqka.com.cn/today_list/index_2.shtml",
        "http://news.10jqka.com.cn/cjkx_list/index_1.shtml",
    ]


def test_tonghuashun_respects_max_pages_for_busy_categories():
    list_html = (FIXTURES / "tonghuashun_list.html").read_text()
    provider = TonghuashunProvider()
    session = RecordingSession(Response(text=list_html))
    provider.session = session

    refs = list(provider.discover(NewsCrawlRequest(categories=("产经新闻",), max_pages=1)))

    assert len(refs) == 1
    assert refs[0].metadata["crawl_hard_limit"] == 1
    assert session.urls == ["http://news.10jqka.com.cn/cjkx_list/index_1.shtml"]


def test_tonghuashun_caps_large_max_pages_at_category_hard_limit():
    list_html = (FIXTURES / "tonghuashun_list.html").read_text()
    provider = TonghuashunProvider()
    session = RecordingSession(Response(text=list_html))
    provider.session = session

    refs = list(provider.discover(NewsCrawlRequest(categories=("产经新闻",), max_pages=50)))

    assert len(refs) == DEFAULT_CATEGORY_HARD_LIMITS["产经新闻"]
    assert refs[0].metadata["crawl_hard_limit"] == DEFAULT_CATEGORY_HARD_LIMITS["产经新闻"]
    assert session.urls[-1] == "http://news.10jqka.com.cn/cjkx_list/index_30.shtml"


def test_tonghuashun_stops_category_when_list_page_404s():
    list_html = (FIXTURES / "tonghuashun_list.html").read_text()
    provider = TonghuashunProvider()
    provider.session = QueueSession([
        Response(text=list_html),
        Response(status_code=404),
    ])

    refs = list(provider.discover(NewsCrawlRequest(
        categories=("产经新闻",),
        category_pages={"产经新闻": 30},
    )))

    assert [ref.section for ref in refs] == ["产经新闻"]


def test_tonghuashun_preserves_stock_subdomain_articles():
    assert _mobile_url("http://stock.10jqka.com.cn/hks/20260625/c123456.shtml") == (
        "http://stock.10jqka.com.cn/hks/20260625/c123456.shtml"
    )


def test_tonghuashun_converts_field_articles_to_mobile():
    assert _mobile_url("http://field.10jqka.com.cn/20260714/c678178722.shtml") == (
        "http://m.10jqka.com.cn/20260714/c678178722.shtml"
    )


def test_tonghuashun_converts_bond_articles_to_mobile():
    assert _mobile_url("http://bond.10jqka.com.cn/20260713/c678147059.shtml") == (
        "http://m.10jqka.com.cn/20260713/c678147059.shtml"
    )
    assert _mobile_url("http://news.10jqka.com.cn/20260625/c123456.shtml") == (
        "http://m.10jqka.com.cn/20260625/c123456.shtml"
    )


def test_tonghuashun_parses_desktop_stock_article():
    provider = TonghuashunProvider()
    provider.session = QueueSession([
        Response(
            text="""
                <html><head><title>港股新闻</title></head><body>
                <h1>港股新闻</h1>
                <div class="date">2026-06-25 10:30:00</div>
                <div class="article-content">这是可提取的桌面端新闻正文。</div>
                </body></html>
            """,
            url="http://stock.10jqka.com.cn/hks/20260625/c123456.shtml",
        ),
    ])
    article = provider.fetch(ArticleRef("tonghuashun", "http://stock.10jqka.com.cn/hks/20260625/c123456.shtml"))
    assert article.title == "港股新闻"
    assert article.content == "这是可提取的桌面端新闻正文。"


def test_tonghuashun_parses_datetime_embedded_in_desktop_script():
    provider = TonghuashunProvider()
    provider.session = QueueSession([
        Response(
            text="""
                <html><head><title>产业新闻</title></head><body>
                <h1>产业新闻</h1>
                <div class="article-content">桌面端正文。</div>
                <script>window.article = {"publishTime": "2026-06-26 05:50:29"};</script>
                </body></html>
            """,
            url="http://field.10jqka.com.cn/20260626/c123456.shtml",
        ),
    ])
    article = provider.fetch(ArticleRef("tonghuashun", "http://field.10jqka.com.cn/20260626/c123456.shtml"))
    assert article.published_at.isoformat().startswith("2026-06-26T05:50:29")


def test_tonghuashun_image_urls_and_ocr_quality_gate():
    assert _image_urls('<p><img src="//e.thsi.cn/img/example"></p>', "https://m.10jqka.com.cn/a") == [
        "https://e.thsi.cn/img/example"
    ]
    assert _usable_ocr_text("交通运输部发布数据显示，端午假期全社会跨区域人员流动总量为六亿多人次。")
    assert not _usable_ocr_text("金融时报 logo")
    assert _normalize_ocr_text("国内出游1.24亿人次\nTS\n78 Eas ous\n同比增长4.4%。") == (
        "国内出游1.24亿人次\n同比增长4.4%。"
    )


def test_guardian_provider_parses_fixture():
    payload = json.loads((FIXTURES / "guardian_search.json").read_text())
    provider = GuardianProvider("test")
    provider.session = RecordingQueueSession([Response(payload=payload)])
    ref = next(iter(provider.discover(NewsCrawlRequest(max_pages=1))))
    article = provider.fetch(ref)
    assert article.title == "Guardian example"
    assert article.section == "Business"
    assert article.tags == ["Stock markets", "Markets", "Example Author"]
    assert article.raw_metadata["type"] == "article"
    assert article.raw_metadata["pillar_name"] == "News"
    assert article.raw_metadata["section_id"] == "business"
    assert article.raw_metadata["section_name"] == "Business"
    assert article.raw_metadata["tag_ids"] == [
        "business/stock-markets",
        "business/markets",
        "profile/example-author",
    ]
    assert article.raw_metadata["tag_types"] == ["keyword", "contributor"]
    assert provider.session.requests[0]["params"]["show-tags"] == "all"


def test_bloomberg_provider_parsers():
    latest = (FIXTURES / "bloomberg_latest.html").read_text()
    api = (FIXTURES / "bloomberg_api.json").read_text()
    article_html = (FIXTURES / "bloomberg_article.html").read_text()
    urls = extract_bloomberg_urls(latest)
    assert len(urls) == 2
    assert extract_bloomberg_api_urls(api) == [
        "https://www.bloomberg.com/news/articles/2026-06-25/api-story",
        "https://www.bloomberg.com/news/articles/2026-06-25/path-story",
    ]
    article = parse_bloomberg_article(article_html, urls[0])
    assert article["title"] == "Bloomberg example"
    assert article["section"] == "Markets"


def test_bloomberg_parses_next_story_article():
    article_html = (FIXTURES / "bloomberg_next_article.html").read_text()
    article = parse_bloomberg_article(article_html, "https://www.bloomberg.com/news/articles/2026-06-25/api-story")
    assert article["title"] == "Bloomberg Next example"
    assert article["summary"] == "Summary from Next data"
    assert article["author"] == "Next Author"
    assert article["section"] == "markets"
    assert article["tags"] == ["markets", "bonds"]
    assert article["content"] == "First Bloomberg paragraph.\nDetails Second paragraph with a link ."


def test_bloomberg_provider_uses_api_before_latest_page():
    api = (FIXTURES / "bloomberg_api.json").read_text()
    provider = BloombergProvider()
    provider.session = RecordingSession(Response(text=api, url="https://www.bloomberg.com/lineup-next/api/stories"))
    provider.uses_curl_cffi = False

    refs = list(provider.discover(NewsCrawlRequest(max_pages=1)))

    assert [ref.url for ref in refs] == [
        "https://www.bloomberg.com/news/articles/2026-06-25/api-story",
        "https://www.bloomberg.com/news/articles/2026-06-25/path-story",
    ]
    assert provider.session.urls[-1] == "https://www.bloomberg.com/lineup-next/api/stories"


def test_bloomberg_parses_chrome_cookies_json_and_validates_login():
    cookies = parse_bloomberg_cookies(json.dumps([
        {"domain": ".bloomberg.com", "name": "_pxhd", "value": "x" * 12},
        {"domain": ".bloomberg.com", "name": "_px2", "value": "x" * 12},
        {"domain": ".bloomberg.com", "name": "session_id", "value": "x" * 12},
        {"domain": ".bloomberg.com", "name": "agent_id", "value": "x" * 12},
        {"domain": ".bloomberg.com", "name": "_breg-uid", "value": "x" * 12},
        {"domain": ".example.com", "name": "ignored", "value": "x" * 12},
    ]))

    assert "ignored" not in cookies
    assert cookies["_breg-uid"] == "x" * 12
    validate_bloomberg_login_cookies(cookies)


def test_bloomberg_login_cookie_validation_requires_breg_uid():
    try:
        validate_bloomberg_login_cookies({"_pxhd": "x" * 12, "_px2": "x" * 12, "session_id": "x" * 12, "agent_id": "x" * 12})
    except BloombergCredentialExpired as exc:
        assert "_breg-uid" in str(exc)
        assert exc.pause_source is True
        assert exc.issue_code == "credential_expired"
    else:
        raise AssertionError("expected missing _breg-uid to fail")


def test_bloomberg_checkpoint_removes_successful_url():
    article_html = (FIXTURES / "bloomberg_article.html").read_text()

    class Checkpoints:
        def __init__(self):
            self.value = {"pending_urls": ["https://www.bloomberg.com/news/articles/2026-06-25/example-story"]}

        def load_checkpoint(self, *_args):
            return dict(self.value)

        def save_checkpoint(self, _source, _key, value):
            self.value = dict(value)

    checkpoints = Checkpoints()
    provider = BloombergProvider(checkpoint_repository=checkpoints)
    provider.session = QueueSession([
        Response(text=article_html, url=checkpoints.value["pending_urls"][0]),
    ])
    provider.fetch(ArticleRef("bloomberg", checkpoints.value["pending_urls"][0]))
    assert checkpoints.value["pending_urls"] == []


def test_politico_provider_parses_feed_fixture():
    feed_xml = (FIXTURES / "politico_feed.xml").read_text()
    refs = parse_politico_feed(feed_xml, "https://rss.politico.com/politics-news.xml", "politics")
    assert len(refs) == 1
    assert refs[0].external_id == "0000019f-example"
    assert refs[0].metadata["author"] == "Jane Reporter"
    assert refs[0].metadata["content"] == "First paragraph from the feed.\nSecond paragraph with markup."

    provider = PoliticoProvider({"politics": "https://rss.politico.com/politics-news.xml"}, discovery_mode="rss")
    provider.session = QueueSession([Response(text=feed_xml)])
    ref = next(iter(provider.discover(NewsCrawlRequest(categories=("politics",), max_articles=1))))
    article = provider.fetch(ref)
    assert article.title == "Politico example"
    assert article.section == "politics"
    assert article.raw_metadata["media_url"] == "https://static.politico.com/example.jpg"


def test_politico_rss_source_uses_separate_source_name():
    feed_xml = (FIXTURES / "politico_feed.xml").read_text()
    refs = parse_politico_feed(
        feed_xml,
        "https://www.politico.com/rss/politicopicks.xml",
        "picks",
        source_name="politico_rss",
    )
    provider = PoliticoProvider(
        {"picks": "https://www.politico.com/rss/politicopicks.xml"},
        discovery_mode="rss",
        source_name="politico_rss",
    )
    provider.session = QueueSession([Response(text=feed_xml)])

    ref = next(iter(provider.discover(NewsCrawlRequest(categories=("picks",), max_articles=1))))
    article = provider.fetch(ref)

    assert refs[0].source_name == "politico_rss"
    assert ref.source_name == "politico_rss"
    assert article.source_name == "politico_rss"


def test_politico_default_feed_uses_current_public_rss_url():
    assert POLITICO_DEFAULT_FEEDS == {"picks": "https://www.politico.com/rss/politicopicks.xml"}


def test_politico_provider_uses_summary_when_feed_has_no_body_without_fetching_page():
    feed_xml = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Politico summary only</title>
      <link>https://www.politico.com/news/2026/06/30/summary-only-00970000</link>
      <description><![CDATA[<p>Summary from free RSS.</p>]]></description>
      <guid isPermaLink="false">summary-only</guid>
      <pubDate>Tue, 30 Jun 2026 09:00:00 EST</pubDate>
    </item>
  </channel>
</rss>"""
    provider = PoliticoProvider({"politics": "https://rss.politico.com/politics-news.xml"}, discovery_mode="rss")
    session = RecordingSession(Response(text=feed_xml))
    provider.session = session

    ref = next(iter(provider.discover(NewsCrawlRequest(categories=("politics",), max_articles=1))))
    article = provider.fetch(ref)

    assert session.urls == ["https://rss.politico.com/politics-news.xml"]
    assert article.title == "Politico summary only"
    assert article.summary == "Summary from free RSS."
    assert article.content == "Summary from free RSS."


def test_politico_provider_falls_back_to_curl_for_cloudflare_blocked_rss():
    feed_xml = (FIXTURES / "politico_feed.xml").read_text()
    provider = PoliticoProvider(
        {"politics": "https://www.politico.com/rss/politicopicks.xml"},
        discovery_mode="rss",
        curl_getter=lambda url, _headers, _timeout: feed_xml,
    )
    provider.session = RecordingSession(Response(text="<html><title>Just a moment...</title></html>", status_code=200))

    ref = next(iter(provider.discover(NewsCrawlRequest(categories=("politics",), max_articles=1))))

    assert ref.url == "https://www.politico.com/news/2026/06/28/example-story-00976940"
    assert provider.session.urls == ["https://www.politico.com/rss/politicopicks.xml"]


def test_politico_provider_discovers_and_fetches_from_news_site():
    news_html = (FIXTURES / "politico_browser_news.html").read_text()
    article_html = (FIXTURES / "politico_browser_article.html").read_text()
    provider = PoliticoProvider(discovery_mode="site", news_url="https://www.politico.com/news/")
    provider.session = QueueSession([
        Response(text=news_html, url="https://www.politico.com/news/"),
        Response(text=article_html, url="https://www.politico.com/news/2026/06/28/first-politico-browser-story-00976940"),
    ])

    ref = next(iter(provider.discover(NewsCrawlRequest(max_articles=1))))
    article = provider.fetch(ref)

    assert ref.source_name == "politico"
    assert ref.url == "https://www.politico.com/news/2026/06/28/first-politico-browser-story-00976940"
    assert article.source_name == "politico"
    assert article.title == "Politico browser example"
    assert article.content == "Politico browser example body."
    assert article.raw_metadata["discovered_from"] == "https://www.politico.com/news/"


def test_politico_site_provider_can_be_named_politico_browser():
    news_html = (FIXTURES / "politico_browser_news.html").read_text()
    article_html = (FIXTURES / "politico_browser_article.html").read_text()
    provider = PoliticoProvider(
        discovery_mode="site",
        news_url="https://www.politico.com/news/",
        source_name="politico_browser",
    )
    provider.session = QueueSession([
        Response(text=news_html, url="https://www.politico.com/news/"),
        Response(text=article_html, url="https://www.politico.com/news/2026/06/28/first-politico-browser-story-00976940"),
    ])

    ref = next(iter(provider.discover(NewsCrawlRequest(max_articles=1))))
    article = provider.fetch(ref)

    assert ref.source_name == "politico_browser"
    assert article.source_name == "politico_browser"
    assert article.title == "Politico browser example"


def test_politico_article_parser_handles_magazine_body_paragraphs():
    article_html = (FIXTURES / "politico_magazine_article.html").read_text()
    provider = PoliticoProvider(discovery_mode="site")
    provider.session = QueueSession([
        Response(text=article_html, url="https://www.politico.com/news/magazine/2026/06/26/example-magazine-00969739"),
    ])

    article = provider.fetch(
        ArticleRef(
            "politico",
            "https://www.politico.com/news/magazine/2026/06/26/example-magazine-00969739",
            section="news",
        )
    )

    assert article.title == "Politico magazine example"
    assert article.summary == "Magazine summary."
    assert article.content == "First magazine paragraph.\nSecond magazine paragraph."
    assert article.section == "Magazine"


def test_politico_provider_retries_article_with_curl_when_parsing_is_empty():
    article_html = (FIXTURES / "politico_magazine_article.html").read_text()
    provider = PoliticoProvider(
        discovery_mode="site",
        curl_getter=lambda url, _headers, _timeout: article_html,
    )
    provider.session = QueueSession([
        Response(text="<html><body>No article here</body></html>", url="https://www.politico.com/news/magazine/2026/06/26/example-magazine-00969739"),
    ])

    article = provider.fetch(
        ArticleRef(
            "politico",
            "https://www.politico.com/news/magazine/2026/06/26/example-magazine-00969739",
            section="news",
        )
    )

    assert article.title == "Politico magazine example"


def test_politico_provider_uses_curl_when_requests_fails():
    provider = PoliticoProvider(
        discovery_mode="site",
        session=FailingSession(requests.ConnectionError("dns failed")),
        curl_getter=lambda url, _headers, _timeout: (FIXTURES / "politico_browser_news.html").read_text(),
    )

    refs = list(provider.discover(NewsCrawlRequest(max_articles=1)))

    assert refs[0].url == "https://www.politico.com/news/2026/06/28/first-politico-browser-story-00976940"


def test_politico_provider_applies_cookie_json_and_proxy_to_requests():
    provider = PoliticoProvider(
        discovery_mode="site",
        proxy="http://proxy.example:8080",
        cookies_json='{"cookies":[{"name":"cf_clearance","value":"token","domain":".politico.com"}]}',
    )

    assert provider.session.headers["Cookie"] == "cf_clearance=token"
    assert provider.session.proxies["https"] == "http://proxy.example:8080"


def test_politico_browser_extracts_news_urls():
    news_html = (FIXTURES / "politico_browser_news.html").read_text()
    assert extract_politico_news_urls(news_html, "https://www.politico.com/news/") == [
        "https://www.politico.com/news/2026/06/28/first-politico-browser-story-00976940",
        "https://www.politico.com/news/2026/06/28/second-politico-browser-story-00976941",
    ]


def test_politico_browser_provider_discovers_and_fetches_article():
    news_html = (FIXTURES / "politico_browser_news.html").read_text()
    article_html = (FIXTURES / "politico_browser_article.html").read_text()
    browser = FakeBrowser({
        "https://www.politico.com/news/": news_html,
        "https://www.politico.com/news/2026/06/28/first-politico-browser-story-00976940": article_html,
    })
    provider = PoliticoBrowserProvider(
        browser_factory=lambda: browser,
        wait_seconds=0,
    )
    ref = next(iter(provider.discover(NewsCrawlRequest(max_articles=1))))
    article = provider.fetch(ref)
    assert ref.source_name == "politico_browser"
    assert article.title == "Politico browser example"
    assert article.source_name == "politico_browser"
    assert article.author == "Browser Reporter"
    assert article.published_at.isoformat() == "2026-06-28T18:50:21+00:00"
    provider.close()
    assert browser.closed


def test_politico_chrome_provider_can_use_separate_source_name():
    news_html = (FIXTURES / "politico_browser_news.html").read_text()
    article_html = (FIXTURES / "politico_browser_article.html").read_text()
    browser = FakeBrowser({
        "https://www.politico.com/news/": news_html,
        "https://www.politico.com/news/2026/06/28/first-politico-browser-story-00976940": article_html,
    })
    provider = PoliticoBrowserProvider(
        browser_factory=lambda: browser,
        wait_seconds=0,
        source_name="politico_chrome",
    )

    ref = next(iter(provider.discover(NewsCrawlRequest(max_articles=1))))
    article = provider.fetch(ref)

    assert ref.source_name == "politico_chrome"
    assert article.source_name == "politico_chrome"


def test_politico_browser_applies_cookies_before_discovery():
    news_html = (FIXTURES / "politico_browser_news.html").read_text()
    browser = FakeBrowser({
        "https://www.politico.com/": "<html><body>home</body></html>",
        "https://www.politico.com/news/": news_html,
    })
    provider = PoliticoBrowserProvider(
        browser_factory=lambda: browser,
        cookies_json='{"name": "cf_clearance", "value": "token", "domain": ".politico.com", "path": "/"}',
        wait_seconds=0,
    )
    ref = next(iter(provider.discover(NewsCrawlRequest(max_articles=1))))
    assert ref.url.endswith("first-politico-browser-story-00976940")
    assert browser.cookies == [
        {"name": "cf_clearance", "value": "token", "domain": ".politico.com", "path": "/"}
    ]


def test_parse_browser_cookies_accepts_export_shapes():
    assert parse_browser_cookies('{"cookies":[{"name":"a","value":"b","expirationDate":1800000000.2}]}') == [
        {"name": "a", "value": "b", "expiry": 1800000000}
    ]


def test_politico_browser_detects_cloudflare_challenge():
    provider = PoliticoBrowserProvider(browser_factory=lambda: FakeBrowser({}), wait_seconds=0)
    for html in (
        '<html><title>Just a moment...</title><script src="https://challenges.cloudflare.com"></script></html>',
        "<html><title>请稍候...</title><body>正在进行安全验证 由 Cloudflare 提供</body></html>",
    ):
        try:
            provider._raise_if_blocked(html, "https://www.politico.com/news/")
        except RuntimeError as exc:
            assert "Cloudflare" in str(exc)
        else:
            raise AssertionError("expected Cloudflare challenge to be detected")


def test_politico_browser_fails_when_no_news_links_are_found():
    browser = FakeBrowser({"https://www.politico.com/news/": "<html><body>No articles</body></html>"})
    provider = PoliticoBrowserProvider(browser_factory=lambda: browser, wait_seconds=0)
    try:
        list(provider.discover(NewsCrawlRequest(max_articles=1)))
    except RuntimeError as exc:
        assert "no news links" in str(exc)
    else:
        raise AssertionError("expected empty discovery to fail")
