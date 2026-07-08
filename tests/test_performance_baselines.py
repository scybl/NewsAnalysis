import json
import time

from stock_pipeline.ops_status import build_ops_snapshot
from stock_pipeline.web import ApiKeyCipher, UserStore


def _archive_item(index: int, *, kind: str) -> dict:
    username = f"{kind}{index:04d}"
    return username, {
        "archived_at": f"20260708_{index % 24:02d}{index % 60:02d}00",
        "archived_by": "admin",
        "reason": f"cleanup-{index}",
        "account": {
            "created_at": f"20260701_{index % 24:02d}0000",
            "created_by": "operator" if kind == "demo" else "",
            "invite_code": f"INV-{index:04d}" if kind == "user" else "",
            "api_keys": {"deepseek": {"ciphertext": "redacted-cipher", "updated_at": "20260708_100000"}} if kind == "user" else {},
        },
        "usage": {"by_path": {"/api/analyze": index % 9, "/api/health": 999}, "last_request_at": "20260708_101100"},
    }


def test_admin_archives_large_payload_performance_baseline(tmp_path):
    archived_users = dict(_archive_item(index, kind="user") for index in range(1200))
    archived_demo_accounts = dict(_archive_item(index, kind="demo") for index in range(1200))
    path = tmp_path / "web_users.json"
    path.write_text(
        json.dumps(
            {
                "users": {},
                "demo_accounts": {},
                "usage": {},
                "archived_users": archived_users,
                "archived_demo_accounts": archived_demo_accounts,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = UserStore(path, ApiKeyCipher("performance-secret"))

    started = time.perf_counter()
    result = store.admin_archives()
    elapsed = time.perf_counter() - started

    assert result["counts"]["total"] == 2400
    assert len(result["items"]) == 2400
    assert elapsed < 3.0


def test_admin_archives_query_performance_baseline(tmp_path):
    archived_users = dict(_archive_item(index, kind="user") for index in range(1000))
    archived_demo_accounts = dict(_archive_item(index, kind="demo") for index in range(1000))
    path = tmp_path / "web_users.json"
    path.write_text(
        json.dumps(
            {
                "users": {},
                "demo_accounts": {},
                "usage": {},
                "archived_users": archived_users,
                "archived_demo_accounts": archived_demo_accounts,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = UserStore(path, ApiKeyCipher("performance-secret"))

    started = time.perf_counter()
    result = store.admin_archives("INV-0999")
    elapsed = time.perf_counter() - started

    assert [item["username"] for item in result["items"]] == ["user0999"]
    assert elapsed < 3.0


def test_ops_snapshot_many_admin_tasks_performance_baseline(tmp_path):
    local_data = tmp_path / "local_data"
    local_data.mkdir()
    tasks = []
    for index in range(1500):
        tasks.append(
            {
                "task_id": f"task-{index}",
                "kind": "news_refetch" if index % 5 else "spider",
                "title": f"后台任务 {index}",
                "status": "running" if index % 13 == 0 else "succeeded",
                "updated_epoch": index,
                "metadata": {"source": "ths_market" if index % 10 == 0 else "guardian"},
                "events": [{"stage": "running", "message": "running"}],
            }
        )
    (local_data / "admin_tasks.json").write_text(json.dumps({"tasks": tasks}, ensure_ascii=False), encoding="utf-8")

    started = time.perf_counter()
    snapshot = build_ops_snapshot(
        tmp_path,
        crawler_snapshot_fn=lambda: {"summary": {"running_count": 0, "expired_running_count": 0}, "alerts": []},
        pid_checker=lambda pid: False,
    )
    elapsed = time.perf_counter() - started

    assert snapshot["tasks"]
    assert len([task for task in snapshot["tasks"] if task["id"].startswith("admin_task:")]) <= 20
    assert elapsed < 3.0
