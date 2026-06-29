import json
from pathlib import Path


def test_contract_declares_news_v1():
    contract = json.loads(
        (Path(__file__).resolve().parents[1] / "contracts" / "raw-article.news.v1.schema.json").read_text()
    )
    assert contract["properties"]["schema_version"]["const"] == "news.v1"
    assert "article_id" in contract["required"]
