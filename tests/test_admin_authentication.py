from stock_pipeline.totp import totp_code


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
    assert web._is_readonly_admin_role("admin_readonly")
    assert not web._is_readonly_admin_role("admin")
