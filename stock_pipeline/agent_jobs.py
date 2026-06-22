from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from .utils import ensure_dir, read_json, timestamp


class PersistentAgentJobStore:
    def __init__(self, path: Path, max_jobs: int = 200, max_idempotency: int = 500):
        self.path = path
        self.max_jobs = max(20, int(max_jobs))
        self.max_idempotency = max(50, int(max_idempotency))
        self.lock = threading.Lock()
        ensure_dir(path.parent)
        self.data = self._load()
        self._mark_interrupted_jobs()

    def create(self, job: dict[str, Any]) -> dict[str, Any]:
        job_id = str(job.get("job_id") or "").strip()
        if not job_id:
            raise ValueError("job_id is required")
        with self.lock:
            self.data.setdefault("jobs", {})[job_id] = self._clone(job)
            self._trim_jobs_locked()
            self._write_locked()
            return self._clone(self.data["jobs"][job_id])

    def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        event: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any] | None:
        with self.lock:
            job = self.data.setdefault("jobs", {}).get(job_id)
            if not job:
                return None
            job["updated_at"] = timestamp()
            job["updated_epoch"] = time.time()
            if status:
                job["status"] = status
                if status in {"succeeded", "failed", "cancelled", "stopped"}:
                    job["finished_at"] = job.get("finished_at") or timestamp()
            if result is not None:
                job["result"] = result
            if error is not None:
                job["error"] = error
            if event:
                events = job.setdefault("progress", [])
                events.append(
                    {
                        "time": event.get("time") or timestamp(),
                        "stage": event.get("stage") or "progress",
                        "message": event.get("message") or "",
                        "details": event.get("details") or {},
                    }
                )
                if len(events) > 200:
                    job["progress"] = events[-200:]
            self._write_locked()
            return self._clone(job)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self.lock:
            job = self.data.get("jobs", {}).get(job_id)
            return self._clone(job) if job else None

    def list(self, *, token_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self.lock:
            items = list(self.data.get("jobs", {}).values())
        if token_id is not None:
            items = [item for item in items if str(item.get("agent_token_id") or "") == token_id]
        items.sort(key=lambda item: float(item.get("updated_epoch") or item.get("created_epoch") or 0), reverse=True)
        return [self._clone(item) for item in items[: max(1, min(200, int(limit or 50)))]]

    def idempotency_get(self, token_id: str, route: str, key: str) -> dict[str, Any] | None:
        if not key:
            return None
        storage_key = self._idempotency_storage_key(token_id, route, key)
        now = time.time()
        with self.lock:
            item = self.data.setdefault("idempotency", {}).get(storage_key)
            if not item:
                return None
            if float(item.get("expires_at") or 0) <= now:
                self.data["idempotency"].pop(storage_key, None)
                self._write_locked()
                return None
            return self._clone(item.get("response") or {})

    def idempotency_put(
        self,
        token_id: str,
        route: str,
        key: str,
        response: dict[str, Any],
        ttl_seconds: int = 86400,
    ) -> None:
        if not key:
            return
        now = time.time()
        storage_key = self._idempotency_storage_key(token_id, route, key)
        with self.lock:
            entries = self.data.setdefault("idempotency", {})
            entries[storage_key] = {
                "token_id": token_id,
                "route": route,
                "key_hash": hashlib.sha256(key.encode("utf-8")).hexdigest(),
                "response": self._clone(response),
                "created_at": timestamp(),
                "created_epoch": now,
                "expires_at": now + max(60, int(ttl_seconds)),
            }
            self._trim_idempotency_locked(now)
            self._write_locked()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "jobs": {}, "idempotency": {}}
        try:
            data = read_json(self.path)
            if not isinstance(data, dict):
                raise ValueError("agent job store must be an object")
        except Exception:
            data = {"version": 1, "jobs": {}, "idempotency": {}}
        data.setdefault("version", 1)
        data.setdefault("jobs", {})
        data.setdefault("idempotency", {})
        return data

    def _mark_interrupted_jobs(self) -> None:
        changed = False
        now = timestamp()
        now_epoch = time.time()
        for job in self.data.get("jobs", {}).values():
            if job.get("status") not in {"queued", "running"}:
                continue
            job["status"] = "failed"
            job["updated_at"] = now
            job["updated_epoch"] = now_epoch
            job["finished_at"] = now
            job["error"] = "服务重启，Agent 任务执行已中断。"
            job.setdefault("progress", []).append(
                {"time": now, "stage": "failed", "message": "服务重启，Agent 任务执行已中断。", "details": {}}
            )
            changed = True
        self._trim_idempotency_locked(now_epoch)
        if changed or self.path.exists():
            self._write_locked()

    def _trim_jobs_locked(self) -> None:
        jobs = self.data.setdefault("jobs", {})
        if len(jobs) <= self.max_jobs:
            return
        ordered = sorted(
            jobs.values(),
            key=lambda item: float(item.get("updated_epoch") or item.get("created_epoch") or 0),
            reverse=True,
        )
        keep = {str(item.get("job_id")) for item in ordered[: self.max_jobs]}
        for job_id in list(jobs):
            if job_id not in keep:
                jobs.pop(job_id, None)

    def _trim_idempotency_locked(self, now: float) -> None:
        entries = self.data.setdefault("idempotency", {})
        for storage_key, item in list(entries.items()):
            if float(item.get("expires_at") or 0) <= now:
                entries.pop(storage_key, None)
        if len(entries) <= self.max_idempotency:
            return
        ordered = sorted(entries.items(), key=lambda pair: float(pair[1].get("created_epoch") or 0), reverse=True)
        self.data["idempotency"] = dict(ordered[: self.max_idempotency])

    def _write_locked(self) -> None:
        ensure_dir(self.path.parent)
        tmp_path = self.path.with_name(f".{self.path.name}.tmp")
        tmp_path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, self.path)
        os.chmod(self.path, 0o600)

    @staticmethod
    def _idempotency_storage_key(token_id: str, route: str, key: str) -> str:
        raw = f"{token_id}\n{route}\n{key}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _clone(value: Any) -> Any:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
