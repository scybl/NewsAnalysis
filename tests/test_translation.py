import hashlib
import json
import urllib.parse

from stock_pipeline.translation import BaiduTranslateClient, BaiduTranslateConfig, _split_text


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps({"trans_result": [{"src": "hello", "dst": "你好"}]}).encode("utf-8")


def test_baidu_translate_client_sends_standard_signed_request(monkeypatch):
    captured = {}

    monkeypatch.setattr("stock_pipeline.translation.random.randint", lambda *_: 12345)

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = request.data.decode("utf-8")
        return FakeResponse()

    monkeypatch.setattr("stock_pipeline.translation.urllib.request.urlopen", fake_urlopen)

    client = BaiduTranslateClient(BaiduTranslateConfig(app_id="app-id", secret_key="secret"), timeout=3)
    assert client.translate("hello", source="en", target="zh") == "你好"

    params = dict(urllib.parse.parse_qsl(captured["body"]))
    expected_sign = hashlib.md5("app-idhello12345secret".encode("utf-8")).hexdigest()
    assert captured["url"].endswith("/api/trans/vip/translate")
    assert captured["timeout"] == 3
    assert params["q"] == "hello"
    assert params["from"] == "en"
    assert params["to"] == "zh"
    assert params["appid"] == "app-id"
    assert params["salt"] == "12345"
    assert params["sign"] == expected_sign


def test_split_text_keeps_chunks_under_limit():
    chunks = _split_text("aaa\nbbb\nccc", 7)
    assert chunks == ["aaa\nbbb", "ccc"]
    assert all(len(chunk) <= 7 for chunk in chunks)
