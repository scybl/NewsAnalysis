import json
from pathlib import Path

from news_crawler.models import NewsCrawlRequest
from news_crawler.models import ArticleRef
from news_crawler.providers.bloomberg import BloombergProvider, extract_bloomberg_urls, parse_bloomberg_article
from news_crawler.providers.guardian import GuardianProvider
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


class RecordingSession:
    def __init__(self, response):
        self.response = response
        self.headers = {}
        self.urls = []

    def get(self, url, **_kwargs):
        self.urls.append(url)
        return self.response


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


def test_tonghuashun_uses_history_based_hard_limits_for_busy_categories():
    list_html = (FIXTURES / "tonghuashun_list.html").read_text()
    provider = TonghuashunProvider()
    session = RecordingSession(Response(text=list_html))
    provider.session = session

    refs = list(provider.discover(NewsCrawlRequest(categories=("产经新闻",), max_pages=1)))

    assert len(refs) == DEFAULT_CATEGORY_HARD_LIMITS["产经新闻"]
    assert refs[0].metadata["crawl_hard_limit"] == DEFAULT_CATEGORY_HARD_LIMITS["产经新闻"]
    assert session.urls[0] == "http://news.10jqka.com.cn/cjkx_list/index_1.shtml"
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
    provider.session = QueueSession([Response(payload=payload)])
    ref = next(iter(provider.discover(NewsCrawlRequest(max_pages=1))))
    article = provider.fetch(ref)
    assert article.title == "Guardian example"
    assert article.section == "Business"


def test_bloomberg_provider_parsers():
    latest = (FIXTURES / "bloomberg_latest.html").read_text()
    article_html = (FIXTURES / "bloomberg_article.html").read_text()
    urls = extract_bloomberg_urls(latest)
    assert len(urls) == 2
    article = parse_bloomberg_article(article_html, urls[0])
    assert article["title"] == "Bloomberg example"
    assert article["section"] == "Markets"


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
