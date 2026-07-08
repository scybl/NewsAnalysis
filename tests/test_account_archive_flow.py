from stock_pipeline.web import ApiKeyCipher, UserStore


def _store(tmp_path) -> UserStore:
    return UserStore(tmp_path / "web_users.json", ApiKeyCipher("archive-flow-secret"), admin_username="admin")


def test_archive_registered_user_flow_removes_active_login_and_preserves_billable_usage(tmp_path):
    store = _store(tmp_path)
    store.seed_invites({"123456"}, ttl_seconds=3600, created_by="admin")
    created, error = store.create_user("alice", "alice-password", "123456")
    assert created is True
    assert error == ""
    store.save_user_api_keys("alice", {"deepseek": "sk-secret", "tushare": ""})
    store.record_usage("alice", "user", "/api/analyze")
    store.record_usage("alice", "user", "/api/analyze")
    store.record_usage("alice", "user", "/api/health")

    result = store.admin_archive_account("alice", actor="admin", reason="manual cleanup")

    assert result == {"kind": "user", "username": "alice"}
    assert store.authenticate_user("alice", "alice-password") is None

    overview = store.admin_overview()
    archives = store.admin_archives()
    archived = archives["items"][0]

    assert all(item["username"] != "alice" for item in overview["users"])
    assert archives["counts"] == {"users": 1, "demo_accounts": 0, "total": 1}
    assert archived["username"] == "alice"
    assert archived["kind"] == "user"
    assert archived["reason"] == "manual cleanup"
    assert archived["usage_total"] == 2
    assert archived["by_path"] == {"/api/analyze": 2}
    assert archived["api_keys"]["deepseek"]["configured"] is True
    assert "sk-secret" not in str(archived)


def test_archive_demo_account_flow_removes_active_demo_and_keeps_usage_snapshot(tmp_path):
    store = _store(tmp_path)
    demo = store.create_demo_account(created_by="admin", limit=3, window_seconds=3600)
    username = demo["username"]
    store.record_usage(username, "demo", "/api/sync-stock-data")
    store.record_usage(username, "demo", "/api/search")

    result = store.admin_archive_account(username, actor="operator", reason="old demo")

    assert result == {"kind": "demo", "username": username}
    assert store.verify_demo_account(username, demo["password"]) is False

    overview = store.admin_overview()
    archives = store.admin_archives(username)
    archived = archives["items"][0]

    assert all(item["username"] != username for item in overview["demo_accounts"])
    assert overview["archived_demo_accounts_count"] == 1
    assert archives["counts"] == {"users": 0, "demo_accounts": 1, "total": 1}
    assert archived["username"] == username
    assert archived["kind"] == "demo"
    assert archived["archived_by"] == "operator"
    assert archived["usage_total"] == 1
    assert archived["by_path"] == {"/api/sync-stock-data": 1}


def test_archived_demo_account_cannot_be_reset_as_active_demo(tmp_path):
    store = _store(tmp_path)
    demo = store.create_demo_account(created_by="admin", limit=3, window_seconds=3600)
    username = demo["username"]

    store.admin_archive_account(username, actor="admin", reason="cleanup")

    try:
        store.admin_reset_demo_budget(username, actor="admin")
    except KeyError as exc:
        assert "找不到测试账号" in str(exc)
    else:
        raise AssertionError("archived demo account should not be reset as an active demo")


def test_archived_usage_only_accounts_do_not_reappear_in_active_overview(tmp_path):
    store = _store(tmp_path)
    store.seed_invites({"111111"}, ttl_seconds=3600, created_by="admin")
    assert store.create_user("bob", "bob-password", "111111")[0] is True
    store.record_usage("bob", "user", "/api/analyze")

    store.admin_archive_account("bob", actor="admin", reason="cleanup")
    overview = store.admin_overview()
    archives = store.admin_archives("bob")

    assert "bob" not in {item["username"] for item in overview["users"]}
    assert "bob" in {item["username"] for item in archives["items"]}


def test_admin_account_is_protected_from_archive(tmp_path):
    store = _store(tmp_path)

    try:
        store.admin_archive_account("admin", actor="admin", reason="nope")
    except PermissionError as exc:
        assert "最高管理员账号不能修改" in str(exc)
    else:
        raise AssertionError("admin archive should be rejected")


def test_archive_unknown_account_raises_readable_error(tmp_path):
    store = _store(tmp_path)

    try:
        store.admin_archive_account("missing-user", actor="admin", reason="cleanup")
    except KeyError as exc:
        assert "找不到用户或测试账号" in str(exc)
    else:
        raise AssertionError("unknown account archive should be rejected")


def test_archive_query_is_case_insensitive_across_account_types(tmp_path):
    store = _store(tmp_path)
    store.seed_invites({"222222"}, ttl_seconds=3600, created_by="admin")
    assert store.create_user("CaseUser", "password", "222222")[0] is True
    demo = store.create_demo_account(created_by="AdminOperator", limit=5, window_seconds=3600)
    store.admin_archive_account("CaseUser", actor="AdminOperator", reason="MixedCase Reason")
    store.admin_archive_account(demo["username"], actor="AdminOperator", reason="DemoCleanup")

    assert [item["username"] for item in store.admin_archives("mixedcase")["items"]] == ["CaseUser"]
    assert {item["username"] for item in store.admin_archives("adminoperator")["items"]} == {demo["username"], "CaseUser"}
    assert [item["username"] for item in store.admin_archives("democleanup")["items"]] == [demo["username"]]
