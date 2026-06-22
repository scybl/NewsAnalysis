from __future__ import annotations

import unittest

from newsanalysis_mcp.security import redact_secrets, wait_for_terminal_job


class SecurityTests(unittest.TestCase):
    def test_redact_secrets_recurses(self) -> None:
        payload = {
            "token": "secret-token",
            "nested": {"password": "secret-password", "value": 3},
            "items": [{"api_key": "secret-key"}],
        }
        redacted = redact_secrets(payload)
        self.assertEqual(redacted["token"], "***")
        self.assertEqual(redacted["nested"]["password"], "***")
        self.assertEqual(redacted["nested"]["value"], 3)
        self.assertEqual(redacted["items"][0]["api_key"], "***")

    def test_wait_for_terminal_job_stops_on_success(self) -> None:
        snapshots = iter([{"status": "running"}, {"status": "succeeded", "result": {"ok": True}}])
        result = wait_for_terminal_job(lambda _job_id: next(snapshots), "job-1", timeout_seconds=2, poll_seconds=0.01)
        self.assertEqual(result["status"], "succeeded")


if __name__ == "__main__":
    unittest.main()
