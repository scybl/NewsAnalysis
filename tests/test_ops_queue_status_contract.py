import json

from stock_pipeline.ops_status import build_ops_snapshot


def test_ops_queue_snapshot_orders_active_items_and_marks_reorderability(tmp_path):
    local_data = tmp_path / "local_data"
    local_data.mkdir()
    (local_data / "task_queue.json").write_text(
        json.dumps(
            {
                "version": 2,
                "items": [
                    {
                        "task_id": "done",
                        "title": "完成任务",
                        "kind": "daily_market",
                        "status": "succeeded",
                        "resource_level": "normal",
                        "manual_priority": 0,
                        "manual_order_index": 0,
                        "enqueued_epoch": 1,
                    },
                    {
                        "task_id": "third-running",
                        "title": "运行中的任务",
                        "kind": "kaipanla",
                        "status": "running",
                        "resource_level": "light_io",
                        "manual_priority": 2,
                        "manual_order_index": 2,
                        "enqueued_epoch": 3,
                        "payload": {"trigger": "manual", "trade_date": "20260719"},
                    },
                    {
                        "task_id": "first",
                        "title": "第一任务",
                        "kind": "daily_market",
                        "status": "queued",
                        "resource_level": "heavy_io",
                        "manual_priority": 0,
                        "manual_order_index": 0,
                        "enqueued_epoch": 4,
                        "payload": {"trigger": "manual", "features": ["a", "b"]},
                    },
                    {
                        "task_id": "second",
                        "title": "第二任务",
                        "kind": "data_random_audit",
                        "status": "deferred",
                        "resource_level": "normal",
                        "manual_priority": 1,
                        "manual_order_index": 1,
                        "run_after_epoch": 9999999999,
                        "enqueued_epoch": 2,
                        "payload": {"resume_checkpoint": {"stage": "daily_rows"}},
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    queue = build_ops_snapshot(tmp_path)["resources"]["task_queue"]
    items = queue["items"]

    assert queue["counts"]["succeeded"] == 1
    assert [item["task_id"] for item in items] == ["first", "second", "third-running"]
    assert [item["reorderable"] for item in items] == [True, True, False]
    assert queue["head"]["task_id"] == "first"
    assert items[0]["payload"]["features"] == 2
    assert items[1]["payload"]["resume_stage"] == "daily_rows"
    assert items[2]["payload"]["trade_date"] == "20260719"


def test_ops_queue_snapshot_hides_raw_payload_fields_from_admin_status(tmp_path):
    local_data = tmp_path / "local_data"
    local_data.mkdir()
    (local_data / "task_queue.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "task_id": "sensitive",
                        "title": "带敏感路径的任务",
                        "kind": "daily_market",
                        "status": "queued",
                        "resource_level": "normal",
                        "enqueued_epoch": 1,
                        "payload": {
                            "trigger": "manual",
                            "ts_code": "000001.SZ",
                            "local_path": "/tmp/private/file.json",
                            "secret": "should-not-leak",
                            "features": ["one"],
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    item = build_ops_snapshot(tmp_path)["resources"]["task_queue"]["items"][0]

    assert item["payload"] == {"trigger": "manual", "ts_code": "000001.SZ", "features": 1}
    assert "local_path" not in json.dumps(item, ensure_ascii=False)
    assert "should-not-leak" not in json.dumps(item, ensure_ascii=False)
