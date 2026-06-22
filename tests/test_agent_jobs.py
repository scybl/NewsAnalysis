from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stock_pipeline.agent_jobs import PersistentAgentJobStore


class PersistentAgentJobStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "agent_jobs.json"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_job_persists_and_can_be_listed_by_token(self) -> None:
        store = PersistentAgentJobStore(self.path)
        store.create(
            {
                "job_id": "job-1",
                "status": "queued",
                "agent_token_id": "token-a",
                "created_epoch": 1,
                "updated_epoch": 1,
                "progress": [],
            }
        )
        store.update("job-1", status="succeeded", result={"rating_hint": "观察"})

        reloaded = PersistentAgentJobStore(self.path)
        job = reloaded.get("job-1")
        self.assertIsNotNone(job)
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(len(reloaded.list(token_id="token-a")), 1)
        self.assertEqual(reloaded.list(token_id="token-b"), [])

    def test_running_job_is_marked_failed_after_restart(self) -> None:
        store = PersistentAgentJobStore(self.path)
        store.create(
            {
                "job_id": "job-running",
                "status": "running",
                "agent_token_id": "token-a",
                "created_epoch": 1,
                "updated_epoch": 1,
                "progress": [],
            }
        )

        reloaded = PersistentAgentJobStore(self.path)
        job = reloaded.get("job-running")
        self.assertEqual(job["status"], "failed")
        self.assertIn("服务重启", job["error"])

    def test_idempotency_survives_restart(self) -> None:
        store = PersistentAgentJobStore(self.path)
        response = {"job_id": "job-1", "status": "queued"}
        store.idempotency_put("token-a", "/analysis-jobs", "stable-key", response)

        reloaded = PersistentAgentJobStore(self.path)
        self.assertEqual(
            reloaded.idempotency_get("token-a", "/analysis-jobs", "stable-key"),
            response,
        )
        self.assertIsNone(reloaded.idempotency_get("token-b", "/analysis-jobs", "stable-key"))


if __name__ == "__main__":
    unittest.main()
