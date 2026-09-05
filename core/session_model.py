"""session_model.py — canonical Aivido project-session model (multi-client).

A ProjectSession is the single unit of isolation for one browser client
working against one Unreal project on the Shadow host. Every field that the
legacy single-project runtime stored in one global (active project, active
map, bridge endpoint, execution id, proof root) lives here per session, so
two clients can drive two projects concurrently without sharing or
corrupting each other's editor instance, maps, execution state, proofs or
Visual Director state.

Storage: one JSON file per session under memory/sessions/{session_id}.json.
The in-memory registry is a cache; the disk file is the source of truth so
separate backend processes see the same sessions.

Status lifecycle:
    STARTING  -> READY  (bridge verified + identity captured)
    READY     -> BUSY   (an action is executing)
    BUSY      -> VALIDATING (mission in visual/technical validation)
    VALIDATING-> READY / BLOCKED / CRASHED
    READY     -> OFFLINE (graceful disconnect)
    any       -> CRASHED (bridge down / editor PID died / identity mismatch)
    CRASHED   -> STARTING (restart requested)
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
SESSION_DIR = ROOT / "memory" / "sessions"

# Canonical session statuses (Phase 1 contract).
STARTING = "STARTING"
READY = "READY"
BUSY = "BUSY"
VALIDATING = "VALIDATING"
BLOCKED = "BLOCKED"
OFFLINE = "OFFLINE"
CRASHED = "CRASHED"

VALID_STATUSES = frozenset(
    {STARTING, READY, BUSY, VALIDATING, BLOCKED, OFFLINE, CRASHED}
)

ACTIVE_STATUSES = frozenset({STARTING, READY, BUSY, VALIDATING, BLOCKED})


@dataclass
class SessionTask:
    """One entry in a session's task queue (execution record)."""

    execution_id: str
    prompt: str
    mode: str = "execute"            # execute | chat | plan
    read_only: bool = False
    status: str = "queued"           # queued | running | validating | done | failed | blocked | queued_resource
    resource_decision: str = "RUNNING"  # RUNNING | QUEUED_RESOURCE | THROTTLED
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    verdict: Optional[str] = None
    why: str = ""
    proof: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "prompt": self.prompt,
            "mode": self.mode,
            "read_only": bool(self.read_only),
            "status": self.status,
            "resource_decision": self.resource_decision,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "verdict": self.verdict,
            "why": self.why,
            "proof": list(self.proof),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionTask":
        return cls(
            execution_id=str(data.get("execution_id") or ""),
            prompt=str(data.get("prompt") or ""),
            mode=str(data.get("mode") or "execute"),
            read_only=bool(data.get("read_only")),
            status=str(data.get("status") or "queued"),
            resource_decision=str(
                data.get("resource_decision") or "RUNNING"),
            created_at=float(data.get("created_at") or time.time()),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            verdict=data.get("verdict"),
            why=str(data.get("why") or ""),
            proof=list(data.get("proof") or []),
        )


@dataclass
class ProjectSession:
    """One isolated client<->project runtime (Phase 1 canonical model)."""

    session_id: str
    client_id: str = "browser"
    project_id: str = ""
    project_path: str = ""           # canonical .uproject path
    project_name: str = ""
    unreal_pid: Optional[int] = None
    bridge_host: str = "127.0.0.1"
    bridge_port: Optional[int] = None
    active_map: str = ""
    engine_version: str = ""
    task_queue: List[SessionTask] = field(default_factory=list)
    current_execution_id: Optional[str] = None
    visual_director_state: Dict[str, Any] = field(default_factory=dict)
    proof_root: str = ""             # assetlib/proof/product/{session_id}
    created_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    status: str = STARTING
    resource_state: Dict[str, Any] = field(default_factory=dict)
    last_error: str = ""
    last_bridge_probe_at: float = 0.0
    launched_by: str = ""            # "reuse" | "launch" | "manual"

    # -- helpers -------------------------------------------------------------
    def touch(self) -> None:
        self.last_seen = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "client_id": self.client_id,
            "project_id": self.project_id,
            "project_path": self.project_path,
            "project_name": self.project_name,
            "unreal_pid": self.unreal_pid,
            "bridge_host": self.bridge_host,
            "bridge_port": self.bridge_port,
            "active_map": self.active_map,
            "engine_version": self.engine_version,
            "task_queue": [t.to_dict() for t in self.task_queue],
            "current_execution_id": self.current_execution_id,
            "visual_director_state": dict(self.visual_director_state),
            "proof_root": self.proof_root,
            "created_at": self.created_at,
            "last_seen": self.last_seen,
            "status": self.status,
            "resource_state": dict(self.resource_state),
            "last_error": self.last_error,
            "last_bridge_probe_at": self.last_bridge_probe_at,
            "launched_by": self.launched_by,
        }

    def summary(self) -> Dict[str, Any]:
        """Concise view for lists/polling (no full queue)."""
        current = self.current_task()
        return {
            "session_id": self.session_id,
            "client_id": self.client_id,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "project_path": self.project_path,
            "status": self.status,
            "bridge": (
                f"{self.bridge_host}:{self.bridge_port}"
                if self.bridge_port else None
            ),
            "unreal_pid": self.unreal_pid,
            "engine_version": self.engine_version,
            "active_map": self.active_map,
            "current_execution_id": self.current_execution_id,
            "current_task": current.status if current else None,
            "task_count": len(self.task_queue),
            "last_seen": self.last_seen,
            "created_at": self.created_at,
            "last_error": self.last_error,
        }

    def current_task(self) -> Optional[SessionTask]:
        if not self.current_execution_id:
            return None
        for t in self.task_queue:
            if t.execution_id == self.current_execution_id:
                return t
        return None

    def get_task(self, execution_id: str) -> Optional[SessionTask]:
        for t in self.task_queue:
            if t.execution_id == execution_id:
                return t
        return None

    def enqueue(self, task: SessionTask) -> None:
        self.task_queue.append(task)
        # bounded history: keep newest 100 records
        if len(self.task_queue) > 100:
            self.task_queue = self.task_queue[-100:]


class SessionStore:
    """Thread-safe, persistent registry of ProjectSession objects."""

    def __init__(self, session_dir: Optional[Path] = None):
        self.dir = Path(session_dir) if session_dir else SESSION_DIR
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._mem: Dict[str, ProjectSession] = {}
        self._load_all()

    # -- persistence ---------------------------------------------------------
    def _path(self, session_id: str) -> Path:
        safe = "".join(
            ch if ch.isalnum() or ch in "-_" else "_"
            for ch in str(session_id)
        )
        return self.dir / f"{safe}.json"

    def _save(self, session: ProjectSession) -> None:
        p = self._path(session.session_id)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(session.to_dict(), indent=2, ensure_ascii=False,
                       default=str),
            encoding="utf-8",
        )
        tmp.replace(p)

    def _load_all(self) -> None:
        for p in self.dir.glob("*.json"):
            if p.name.endswith(".tmp"):
                continue
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            try:
                session = self._from_dict(data)
            except Exception:
                continue
            self._mem[session.session_id] = session

    def _from_dict(self, data: Dict[str, Any]) -> ProjectSession:
        queue = [
            SessionTask.from_dict(t) for t in (data.get("task_queue") or [])
        ]
        return ProjectSession(
            session_id=str(data.get("session_id") or ""),
            client_id=str(data.get("client_id") or "browser"),
            project_id=str(data.get("project_id") or ""),
            project_path=str(data.get("project_path") or ""),
            project_name=str(data.get("project_name") or ""),
            unreal_pid=data.get("unreal_pid"),
            bridge_host=str(data.get("bridge_host") or "127.0.0.1"),
            bridge_port=data.get("bridge_port"),
            active_map=str(data.get("active_map") or ""),
            engine_version=str(data.get("engine_version") or ""),
            task_queue=queue,
            current_execution_id=data.get("current_execution_id"),
            visual_director_state=dict(data.get("visual_director_state") or {}),
            proof_root=str(data.get("proof_root") or ""),
            created_at=float(data.get("created_at") or time.time()),
            last_seen=float(data.get("last_seen") or time.time()),
            status=str(data.get("status") or STARTING),
            resource_state=dict(data.get("resource_state") or {}),
            last_error=str(data.get("last_error") or ""),
            last_bridge_probe_at=float(
                data.get("last_bridge_probe_at") or 0.0),
            launched_by=str(data.get("launched_by") or ""),
        )

    # -- CRUD -----------------------------------------------------------------
    def create(
        self,
        project_id: str,
        project_path: str,
        *,
        client_id: str = "browser",
        project_name: str = "",
    ) -> ProjectSession:
        with self._lock:
            session_id = f"sess_{uuid.uuid4().hex[:10]}"
            session = ProjectSession(
                session_id=session_id,
                client_id=client_id,
                project_id=project_id,
                project_path=str(project_path),
                project_name=project_name or Path(str(project_path)).stem,
                status=STARTING,
            )
            self._mem[session_id] = session
            self._save(session)
            return session

    def get(self, session_id: str) -> Optional[ProjectSession]:
        with self._lock:
            return self._mem.get(session_id)

    def require(self, session_id: str) -> ProjectSession:
        session = self.get(session_id)
        if session is None:
            raise KeyError(f"unknown session: {session_id}")
        return session

    def list(self) -> List[ProjectSession]:
        with self._lock:
            return sorted(
                self._mem.values(),
                key=lambda s: s.created_at,
                reverse=True,
            )

    def save(self, session: ProjectSession) -> None:
        with self._lock:
            self._mem[session.session_id] = session
            self._save(session)

    def update(
        self, session_id: str, fn, *args, **kwargs
    ) -> Optional[ProjectSession]:
        """Apply fn(session, *args, **kwargs) and persist. Returns session."""
        with self._lock:
            session = self._mem.get(session_id)
            if session is None:
                return None
            result = fn(session, *args, **kwargs)
            session.touch()
            self._save(session)
            return session if result is None else result

    def touch(self, session_id: str) -> None:
        self.update(session_id, lambda s: None)

    def set_status(self, session_id: str, status: str,
                   error: str = "") -> Optional[ProjectSession]:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid session status: {status!r}")
        return self.update(
            session_id,
            lambda s, st, err: (
                setattr(s, "status", st),
                setattr(s, "last_error", err or s.last_error),
            ) and None,
            status,
            error,
        )

    def set_execution(
        self, session_id: str, execution_id: Optional[str],
        task_status: str = "running",
    ) -> None:
        def _apply(s: ProjectSession) -> None:
            s.current_execution_id = execution_id
            if execution_id:
                task = s.get_task(execution_id)
                if task:
                    task.status = task_status
                    task.started_at = task.started_at or time.time()
        self.update(session_id, _apply)

    def finish_execution(
        self, session_id: str, execution_id: str, verdict: str,
        why: str = "", proof: Optional[List[str]] = None,
        status: str = READY,
    ) -> None:
        def _apply(s: ProjectSession) -> None:
            if s.current_execution_id == execution_id:
                s.current_execution_id = None
            task = s.get_task(execution_id)
            if task:
                task.status = (
                    "done" if verdict == "PASS"
                    else "cancelled" if verdict == "CANCELLED"
                    else "blocked" if verdict == "BLOCKED"
                    else "failed"
                )
                task.verdict = verdict
                task.why = why or task.why
                task.finished_at = time.time()
                if proof:
                    task.proof = list(proof)
            s.status = status
        self.update(session_id, _apply)

    def remove(self, session_id: str) -> bool:
        with self._lock:
            self._mem.pop(session_id, None)
            try:
                self._path(session_id).unlink(missing_ok=True)
            except OSError:
                pass
            return True

    def sessions_for_project(self, project_id: str) -> List[ProjectSession]:
        return [s for s in self.list() if s.project_id == project_id]

    def active_for_project(self, project_id: str) -> List[ProjectSession]:
        return [
            s for s in self.sessions_for_project(project_id)
            if s.status in ACTIVE_STATUSES
        ]

    # -- stale sweep -----------------------------------------------------------
    def mark_stale_offline(self, stale_seconds: float = 90.0) -> int:
        """Sessions not seen recently become OFFLINE (never CRASHED here —
        the bridge health probe owns crash detection)."""
        now = time.time()
        marked = 0
        for s in self.list():
            if s.status in ACTIVE_STATUSES \
                    and (now - s.last_seen) > stale_seconds:
                self.set_status(s.session_id, OFFLINE,
                                error="no heartbeat within "
                                      f"{int(stale_seconds)}s")
                marked += 1
        return marked