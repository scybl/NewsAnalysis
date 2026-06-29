from stock_pipeline.web import _secure_text_equal, redact_local_paths


def test_secure_text_equal_supports_non_ascii_credentials():
    assert _secure_text_equal("管理员密码", "管理员密码")
    assert not _secure_text_equal("管理员密码", "其他密码")


def test_redact_local_paths_removes_nested_filesystem_locations():
    payload = {
        "ok": True,
        "local_dir": "/app/local_data/000001.SZ/current",
        "items": [
            {
                "location": "current",
                "analysis_path": "/app/local_data/000001.SZ/current/value_speculation.md",
                "updated_at": "20260626_213101",
            }
        ],
        "datasets": [{"key": "daily", "records": [{"close": 12.3}]}],
    }

    redacted = redact_local_paths(payload)

    assert "local_dir" not in redacted
    assert "analysis_path" not in redacted["items"][0]
    assert redacted["items"][0]["updated_at"] == "20260626_213101"
    assert redacted["datasets"][0]["records"][0]["close"] == 12.3
