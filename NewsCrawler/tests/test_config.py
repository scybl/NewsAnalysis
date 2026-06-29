from news_crawler.config import _mongo_uri


def test_mongo_uri_uses_local_secret_file_by_default(tmp_path, monkeypatch):
    secret_dir = tmp_path / "local_data" / "secure"
    secret_dir.mkdir(parents=True)
    (secret_dir / "mongo_root_password.txt").write_text("secret", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.delenv("MONGO_USER", raising=False)
    monkeypatch.delenv("MONGO_PASSWORD", raising=False)
    monkeypatch.delenv("MONGO_PASSWORD_FILE", raising=False)
    monkeypatch.setenv("MONGO_HOST", "127.0.0.1")
    monkeypatch.setenv("MONGO_PORT", "27017")

    assert _mongo_uri() == "mongodb://admin:secret@127.0.0.1:27017/?authSource=admin"
