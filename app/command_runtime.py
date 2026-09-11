from __future__ import annotations

import hashlib
import json
import queue
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional

TERMINAL = {"pass", "failed", "cancelled"}

class CommandRuntime:
    def __init__(self, executor: Callable[[str], Any], state_path: Path) -> None:
        self.executor = executor
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._request_index: Dict[str, str] = {}
        self._stop = threading.Event()
        self._load()
        self._recover()
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="aivido-command-worker",
            daemon=True,
        )
        self._worker.start()

    @staticmethod
    def _now() -> float:
        return time.time()

    @staticmethod
    def _hash_message(message: str) -> str:
        return hashlib.sha256(message.strip().encode("utf-8")).hexdigest()

    def _snapshot(self) -> Dict[str, Any]:
        return {
            "version": 1,
            "jobs": self._jobs,
            "request_index": self._request_index,
        }

    def _persist(self) -> None:
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(self._snapshot(), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        tmp.replace(self.state_path)

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            jobs = raw.get("jobs", {})
            idx = raw.get("request_index", {})
            if isinstance(jobs, dict):
                self._jobs = jobs
            if isinstance(idx, dict):
                self._request_index = idx
        except Exception:
            self._jobs = {}
            self._request_index = {}

    def _recover(self) -> None:
        now = self._now()
        changed = False
        for job_id, job in list(self._jobs.items()):
            state = str(job.get("state", ""))
            if state == "queued":
                self._queue.put(job_id)
            elif state == "running":
                job["state"] = "failed"
                job["error"] = "runtime_restarted_during_execution"
                job["finished_at"] = now
                job["updated_at"] = now
                job["progress"] = 100
                changed = True
        if changed:
            self._persist()

    def submit(self, message: str, request_id: Optional[str] = None) -> Dict[str, Any]:
        text = str(message or "").strip()
        if not text:
            raise ValueError("message_required")
        rid = str(request_id or "").strip() or uuid.uuid4().hex
        with self._lock:
            existing_id = self._request_index.get(rid)
            if existing_id and existing_id in self._jobs:
                return dict(self._jobs[existing_id])

            job_id = "cmd_" + uuid.uuid4().hex[:16]
            now = self._now()
            job = {
                "job_id": job_id,
                "request_id": rid,
                "message": text,
                "message_sha256": self._hash_message(text),
                "state": "queued",
                "progress": 0,
                "created_at": now,
                "updated_at": now,
                "started_at": None,
                "finished_at": None,
                "result": None,
                "error": None,
                "cancel_requested": False,
                "attempt": 1,
            }
            self._jobs[job_id] = job
            self._request_index[rid] = job_id
            self._persist()
            self._queue.put(job_id)
            return dict(job)

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def evidence(self, job_id: str) -> Optional[Dict[str, Any]]:
        job = self.get(job_id)
        if not job:
            return None
        return {
            "job_id": job["job_id"],
            "state": job["state"],
            "progress": job.get("progress", 0),
            "attempt": job.get("attempt", 1),
            "created_at": job.get("created_at"),
            "started_at": job.get("started_at"),
            "finished_at": job.get("finished_at"),
            "result": job.get("result"),
            "error": job.get("error"),
            "message_sha256": job.get("message_sha256"),
        }

    def cancel(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            if job["state"] == "queued":
                job["state"] = "cancelled"
                job["progress"] = 100
                job["cancel_requested"] = True
                job["finished_at"] = self._now()
                job["updated_at"] = self._now()
                self._persist()
            elif job["state"] == "running":
                job["cancel_requested"] = True
                job["updated_at"] = self._now()
                self._persist()
            return dict(job)

    def retry(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            old = self._jobs.get(job_id)
            if not old:
                return None
            if old["state"] not in {"failed", "cancelled"}:
                return dict(old)
            return self.submit(
                old["message"],
                request_id=f'{old["request_id"]}:retry:{int(self._now())}',
            )

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            counts: Dict[str, int] = {}
            for job in self._jobs.values():
                state = str(job.get("state", "unknown"))
                counts[state] = counts.get(state, 0) + 1
            active = next(
                (dict(job) for job in self._jobs.values() if job.get("state") == "running"),
                None,
            )
            return {
                "ok": True,
                "worker_alive": self._worker.is_alive(),
                "counts": counts,
                "active": active,
                "state_path": str(self.state_path),
            }

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                job_id = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._execute(job_id)
            finally:
                self._queue.task_done()

    def _execute(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job["state"] != "queued":
                return
            if job.get("cancel_requested"):
                job["state"] = "cancelled"
                job["progress"] = 100
                job["finished_at"] = self._now()
                job["updated_at"] = self._now()
                self._persist()
                return
            job["state"] = "running"
            job["progress"] = 10
            job["started_at"] = self._now()
            job["updated_at"] = self._now()
            self._persist()
            message = job["message"]

        try:
            result = self.executor(message)
            with self._lock:
                job = self._jobs[job_id]
                if job.get("cancel_requested"):
                    job["state"] = "cancelled"
                    job["error"] = "cancel_requested_during_execution"
                else:
                    job["state"] = "pass"
                    job["result"] = result
                job["progress"] = 100
                job["finished_at"] = self._now()
                job["updated_at"] = self._now()
                self._persist()
        except Exception as exc:
            with self._lock:
                job = self._jobs[job_id]
                job["state"] = "failed"
                job["progress"] = 100
                job["error"] = f"{type(exc).__name__}: {exc}"
                job["finished_at"] = self._now()
                job["updated_at"] = self._now()
                self._persist()
