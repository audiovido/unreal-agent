"""
Supervisor state management and JSON persistence.

Maintains:
  - task queue (ordered list of tasks)
  - worker status and assignment
  - attempt counts, PASS/FAIL results
  - timestamps and final completion state
  - file locks to prevent concurrent edits
  - checkpoint data for risky operations
"""

from __future__ import annotations

import json
import os
import time
import uuid
import threading
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "memory" / "supervisor"
STATE_FILE = STATE_DIR / "supervisor_state.json"
LOCKS_DIR = STATE_DIR / "locks"
CHECKPOINTS_DIR = STATE_DIR / "checkpoints"

# Safety limits
MAX_RETRIES = 5
MAX_WORKERS = 2


def ensure_dirs():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LOCKS_DIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINTS_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass
class Task:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    prompt: str = ""
    worker_id: str | None = None  # assigned worker
    status: str = "queued"  # queued | assigned | running | passed | failed | blocked
    attempt: int = 0
    max_attempts: int = MAX_RETRIES
    result: Any = None
    last_output: str = ""
    pass_fail: str | None = None  # "PASS" or "FAIL"
    error: str | None = None
    blocked_reason: str | None = None
    followup_prompt: str | None = None
    created_at: float = field(default_factory=time.time)
    assigned_at: float | None = None
    started_at: float | None = None
    finished_at: float | None = None
    locked_files: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict):
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class WorkerState:
    id: str = ""
    name: str = ""
    role: str = ""  # e.g. "core_backend" or "ui_integration"
    status: str = "idle"  # idle | busy | error | stopped
    current_task_id: str | None = None
    tasks_completed: int = 0
    tasks_failed: int = 0
    last_heartbeat: float = field(default_factory=time.time)
    last_output: str = ""
    error: str | None = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict):
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class SupervisorState:
    status: str = "idle"  # idle | running | paused | stopped
    workers: list[WorkerState] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    completed_tasks: list[Task] = field(default_factory=list)
    activity_log: list[dict[str, Any]] = field(default_factory=list)
    started_at: float | None = None
    last_tick: float | None = None
    total_cycles: int = 0

    def to_dict(self):
        return {
            "status": self.status,
            "workers": [w.to_dict() for w in self.workers],
            "tasks": [t.to_dict() for t in self.tasks],
            "completed_tasks": [t.to_dict() for t in self.completed_tasks],
            "activity_log": self.activity_log[-500:],
            "started_at": self.started_at,
            "last_tick": self.last_tick,
            "total_cycles": self.total_cycles,
        }

    @classmethod
    def from_dict(cls, d: dict):
        s = cls()
        s.status = d.get("status", "idle")
        s.workers = [WorkerState.from_dict(w) for w in d.get("workers", [])]
        s.tasks = [Task.from_dict(t) for t in d.get("tasks", [])]
        s.completed_tasks = [Task.from_dict(t) for t in d.get("completed_tasks", [])]
        s.activity_log = d.get("activity_log", [])
        s.started_at = d.get("started_at")
        s.last_tick = d.get("last_tick")
        s.total_cycles = d.get("total_cycles", 0)
        return s


# ============================================================
# PERSISTENCE
# ============================================================

_lock = threading.Lock()


def save_state(state: SupervisorState):
    ensure_dirs()
    with _lock:
        tmp = STATE_DIR / f"state.{uuid.uuid4().hex}.tmp"
        data = state.to_dict()
        tmp.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        for attempt in range(8):
            try:
                tmp.replace(STATE_FILE)
                return
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(0.05 * (attempt + 1))


def load_state() -> SupervisorState:
    ensure_dirs()
    with _lock:
        if not STATE_FILE.exists():
            return SupervisorState()
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return SupervisorState.from_dict(data)
        except Exception:
            return SupervisorState()


def log_activity(state: SupervisorState, kind: str, text: str, **extra):
    entry = {
        "id": str(uuid.uuid4()),
        "kind": kind,
        "text": text,
        "timestamp": time.time(),
        **extra,
    }
    state.activity_log.append(entry)
    if len(state.activity_log) > 500:
        state.activity_log = state.activity_log[-500:]


# ============================================================
# FILE LOCKING
# ============================================================

class FileLock:
    """Simple file-based lock to prevent concurrent edits."""

    def __init__(self, lock_name: str, timeout: float = 300):
        self.lock_name = lock_name
        self.lock_path = LOCKS_DIR / f"{lock_name}.lock"
        self.timeout = timeout
        self._acquired = False

    def acquire(self) -> bool:
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            if not self.lock_path.exists():
                try:
                    fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    os.write(fd, json.dumps({
                        "holder": str(uuid.uuid4()),
                        "acquired_at": time.time(),
                    }).encode())
                    os.close(fd)
                    self._acquired = True
                    return True
                except FileExistsError:
                    # Lock exists — check if stale (> timeout * 2)
                    try:
                        data = json.loads(self.lock_path.read_text())
                        age = time.time() - data.get("acquired_at", 0)
                        if age > self.timeout * 2:
                            self.lock_path.unlink(missing_ok=True)
                            continue
                    except Exception:
                        self.lock_path.unlink(missing_ok=True)
                        continue
            time.sleep(0.2)
        return False

    def release(self):
        if self._acquired and self.lock_path.exists():
            try:
                self.lock_path.unlink()
            except Exception:
                pass
            self._acquired = False

    def __enter__(self):
        if not self.acquire():
            raise TimeoutError(f"Could not acquire lock: {self.lock_name}")
        return self

    def __exit__(self, *args):
        self.release()


def release_all_locks():
    """Clear all stale locks (e.g. on supervisor restart)."""
    ensure_dirs()
    for f in LOCKS_DIR.glob("*.lock"):
        try:
            data = json.loads(f.read_text())
            age = time.time() - data.get("acquired_at", 0)
            if age > 600:  # 10 min stale
                f.unlink(missing_ok=True)
        except Exception:
            f.unlink(missing_ok=True)


# ============================================================
# CHECKPOINTING
# ============================================================

def create_checkpoint(label: str, files: list[str]) -> str:
    """Snapshot files before risky edits. Returns checkpoint ID."""
    cp_id = f"{label}_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    cp_dir = CHECKPOINTS_DIR / cp_id
    cp_dir.mkdir(parents=True, exist_ok=True)

    manifest = []
    for fpath in files:
        src = Path(fpath)
        if src.exists() and src.is_file():
            dst = cp_dir / src.name
            dst.write_bytes(src.read_bytes())
            manifest.append({"path": str(src), "size": src.stat().st_size})

    (cp_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    return cp_id


def restore_checkpoint(cp_id: str) -> bool:
    cp_dir = CHECKPOINTS_DIR / cp_id
    if not cp_dir.exists():
        return False
    manifest_path = cp_dir / "manifest.json"
    if not manifest_path.exists():
        return False
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for item in manifest:
        src = cp_dir / Path(item["path"]).name
        dst = Path(item["path"])
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
    return True
