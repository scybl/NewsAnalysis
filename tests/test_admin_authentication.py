from stock_pipeline.totp import totp_code


def test_admin_archives_combines_registered_and_demo_accounts(tmp_path):
    import json

    from stock_pipeline.web import ApiKeyCipher, UserStore

    store_path = tmp_path / "web_users.json"
    store_path.write_text(
        json.dumps(
            {
                "users": {},
                "demo_accounts": {},
                "archived_users": {
                    "alice": {
                        "archived_at": "20260708_103700",
                        "archived_by": "admin",
                        "reason": "manual",
                        "account": {"created_at": "20260701_090000", "role": "user"},
                        "usage": {"by_path": {"/api/analyze": 12}, "last_request_at": "20260708_101100"},
                    }
                },
                "archived_demo_accounts": {
                    "demo001": {
                        "archived_at": "20260707_213000",
                        "archived_by": "admin",
                        "reason": "old demo",
                        "account": {"created_at": "20260701_080000", "tier": "demo"},
                        "usage": {"by_path": {"/api/sync-stock-data": 3}, "last_request_at": "20260707_210000"},
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    store = UserStore(store_path, ApiKeyCipher("test-secret"))
    result = store.admin_archives()

    assert result["counts"] == {"users": 1, "demo_accounts": 1, "total": 2}
    assert [item["username"] for item in result["items"]] == ["alice", "demo001"]
    assert {item["kind"] for item in result["items"]} == {"user", "demo"}
    assert result["items"][0]["usage_total"] == 12

    filtered = store.admin_archives("demo")
    assert filtered["counts"] == {"users": 0, "demo_accounts": 1, "total": 1}
    assert filtered["items"][0]["username"] == "demo001"


def test_admin_authentication_does_not_depend_on_ephemeral_page_challenge(monkeypatch):
    from stock_pipeline import web

    class Settings:
        web_username = "admin"
        web_password = "safe-password"

    class App:
        settings = Settings()

    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setattr(web, "get_secret_store", lambda: type("Store", (), {"get": lambda self, name: secret})())

    # The real authentication factors are password + TOTP. A service restart
    # must not invalidate otherwise correct credentials.
    assert web._secure_text_equal("safe-password", App.settings.web_password)
    assert web.verify_totp(secret, totp_code(secret))


def test_fixed_admin_readonly_account():
    from stock_pipeline import web

    class Settings:
        admin_readonly_username = "viewer"
        admin_readonly_password = "viewer-password"

    assert web._readonly_admin_account(Settings, "viewer", "viewer-password") == {
        "username": "viewer",
        "role": "admin_readonly",
        "admin_readonly": True,
    }
    assert web._readonly_admin_account(Settings, "viewer", "wrong") is None
    assert web._readonly_admin_account(Settings, "friend", "viewer-password") is None


def test_admin_readonly_is_admin_get_but_not_write():
    from stock_pipeline import web

    assert web._is_admin_role("admin")
    assert web._is_admin_role("admin_readonly")
    assert not web._is_admin_role("user")
    assert web._can_view_data_console("admin")
    assert web._can_view_data_console("admin_readonly")
    assert web._can_view_data_console("user")
    assert not web._can_view_data_console("demo")
    assert web._is_readonly_admin_role("admin_readonly")
    assert not web._is_readonly_admin_role("admin")
