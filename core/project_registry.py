"""project_registry.py — persistent Aivido project registry (multi-client).

The registry is the durable list of Unreal projects Aivido may run sessions
against. It never scans arbitrary filesystem roots through the API: a project
can only be registered by an explicit, validated .uproject path (must exist
and parse). Each record carries its own bridge configuration, last map,
proof directory and health, so no global active-project assumption leaks
between projects.

API surface (also exposed over HTTP in app/session_api.py):
    list_projects / register_project / get_project / update_project
    remove_project / inspect_project / connect_project / disconnect_project
    start_project_session (creates + starts a session for the project)
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import app_config

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_FILE = ROOT / "config" / "project_registry.json"
PROOF_ROOT = ROOT / "assetlib" / "proof" / "product"

_HEALTH_OK = "OK"
_HEALTH_UNREACHABLE = "UNREACHABLE"
_HEALTH_UNKNOWN = "UNKNOWN"

# Allowed statuses for a registered project.
PROJECT_STATUSES = frozenset({"registered", "connected", "disconnected"})


def validate_uproject_path(path: Optional[str]) -> Dict[str, Any]:
    """Validate an explicit .uproject path. No globbing, no search: the API
    accepts only paths that exist and parse, so arbitrary filesystem access
    is never exposed."""
    if not path or not str(path).strip():
        return {"ok": False, "error": "uproject path is required"}
    p = Path(str(path).strip())
    if p.suffix.lower() != ".uproject":
        return {"ok": False, "error": f"not a .uproject file: {p.name}"}
    if not p.exists():
        return {"ok": False, "error": f"project file not found: {p}"}
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"ok": False, "error": f"unparseable .uproject: {exc}"}
    engine = data.get("EngineAssociation")
    return {
        "ok": True,
        "uproject_path": str(p.resolve()).replace("\\", "/"),
        "project_name": p.stem,
        "engine_association": str(engine) if engine else None,
        "project_root": str(p.parent),
    }


def default_proof_dir(project_id: str) -> str:
    return str(PROOF_ROOT / f"projects/{project_id}")


class ProjectRegistry:
    """Thread-safe persistent project registry."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else REGISTRY_FILE
        self._lock = threading.RLock()
        self._mem: Dict[str, Dict[str, Any]] = {}
        self._load()

    # -- persistence ---------------------------------------------------------
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except Exception:
            return
        projects = data.get("projects") if isinstance(data, dict) else None
        if isinstance(projects, list):
            for rec in projects:
                pid = rec.get("project_id")
                if pid:
                    self._mem[pid] = rec

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(
                {"schema": "ua.project_registry.v1",
                 "projects": sorted(
                     self._mem.values(), key=lambda r: r["project_id"])},
                indent=2, ensure_ascii=False, default=str,
            ),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    # -- CRUD -----------------------------------------------------------------
    def register(self, uproject_path: str, *,
                 display_name: Optional[str] = None,
                 preferred_engine: Optional[str] = None,
                 bridge_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Register a project by validated explicit path (Phase 2)."""
        with self._lock:
            validated = validate_uproject_path(uproject_path)
            if not validated.get("ok"):
                return validated
            path = validated["uproject_path"]
            # Re-register returns the existing record (idempotent).
            for pid, rec in self._mem.items():
                if rec.get("uproject_path") == path:
                    return {"ok": True, "project": self._public(pid, rec),
                            "already_registered": True}
            project_id = f"proj_{uuid.uuid4().hex[:8]}"
            now = time.time()
            rec: Dict[str, Any] = {
                "project_id": project_id,
                "display_name": display_name or validated["project_name"],
                "uproject_path": path,
                "project_root": validated["project_root"],
                "engine_association": validated["engine_association"],
                "preferred_engine": preferred_engine
                or validated["engine_association"] or "5.8",
                "bridge_config": dict(bridge_config or {}),
                "last_map": "",
                "proof_directory": default_proof_dir(project_id),
                "project_health": _HEALTH_UNKNOWN,
                "status": "registered",
                "connected_session_id": None,
                "registered_at": now,
                "last_connected_at": None,
                "last_error": "",
            }
            self._mem[project_id] = rec
            self._save()
            return {"ok": True, "project": self._public(project_id, rec)}

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [self._public(pid, rec)
                    for pid, rec in sorted(
                        self._mem.items(),
                        key=lambda kv: kv[1].get("display_name", "").lower())]

    def get(self, project_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            rec = self._mem.get(project_id)
            return self._public(project_id, rec) if rec else None

    def require(self, project_id: str) -> Dict[str, Any]:
        rec = self.get(project_id)
        if rec is None:
            raise KeyError(f"unknown project: {project_id}")
        return rec

    def _update(self, project_id: str, fn) -> Optional[Dict[str, Any]]:
        with self._lock:
            rec = self._mem.get(project_id)
            if rec is None:
                return None
            fn(rec)
            self._save()
            return self._public(project_id, rec)

    def update(self, project_id: str, **fields) -> Optional[Dict[str, Any]]:
        def _apply(rec: Dict[str, Any]) -> None:
            for key, value in fields.items():
                if key in rec:
                    rec[key] = value
        return self._update(project_id, _apply)

    def remove(self, project_id: str) -> bool:
        with self._lock:
            if project_id not in self._mem:
                return False
            del self._mem[project_id]
            self._save()
            return True

    # -- project API -----------------------------------------------------------
    def connect(self, project_id: str, session_id: Optional[str] = None,
                bridge_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Mark the project connected (a live session owns it)."""
        def _apply(rec: Dict[str, Any]) -> None:
            if bridge_config:
                rec["bridge_config"] = dict(bridge_config)
            rec["connected_session_id"] = session_id
            rec["status"] = "connected" if session_id else "registered"
            rec["last_connected_at"] = time.time()
            rec["project_health"] = _HEALTH_OK
            rec["last_error"] = ""
        updated = self._update(project_id, _apply)
        return {"ok": True, "project": updated}

    def disconnect(self, project_id: str) -> Dict[str, Any]:
        def _apply(rec: Dict[str, Any]) -> None:
            rec["connected_session_id"] = None
            rec["status"] = "disconnected"
        updated = self._update(project_id, _apply)
        return {"ok": True, "project": updated}

    def inspect(self, project_id: str) -> Dict[str, Any]:
        """Read-only project inspection: registry record + a live bridge probe
        when a session is connected. Never mutates."""
        rec = self.require(project_id)
        out = dict(rec)
        session_id = rec.get("connected_session_id")
        if session_id:
            try:
                from core.session_execution import session_bridge_for
                bridge = session_bridge_for(session_id)
                if bridge is not None:
                    identity = bridge.get_project_identity()
                    payload = identity.get("result") if isinstance(
                        identity, dict) else None
                    if isinstance(payload, dict) and payload.get("ok"):
                        out["live_identity"] = payload
            except Exception as exc:
                out["inspect_error"] = f"{type(exc).__name__}: {exc}"
        return out

    def start_project_session(
        self, project_id: str, *, client_id: str = "browser",
        session_store=None, runner=None,
    ) -> Dict[str, Any]:
        """Phase 2 'start Unreal project session': create a session for the
        project and start its bridge. Requires the session runner."""
        rec = self.require(project_id)
        if session_store is None:
            from core.session_model import SessionStore
            session_store = SessionStore()
        session = session_store.create(
            project_id=project_id,
            project_path=rec["uproject_path"],
            client_id=client_id,
            project_name=rec["display_name"],
        )
        if runner is None:
            from core.session_execution import get_default_runner
            runner = get_default_runner()
        result = runner.start_project(session)
        if result.get("ok"):
            self.connect(
                project_id, session_id=session.session_id,
                bridge_config={
                    "host": session.bridge_host,
                    "port": session.bridge_port,
                },
            )
        return {**result, "session_id": session.session_id,
                "project_id": project_id}

    # -- shaping ---------------------------------------------------------------
    @staticmethod
    def _public(project_id: str, rec: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "project_id": project_id,
            "display_name": rec.get("display_name"),
            "uproject_path": rec.get("uproject_path"),
            "preferred_engine": rec.get("preferred_engine"),
            "engine_association": rec.get("engine_association"),
            "bridge_config": dict(rec.get("bridge_config") or {}),
            "last_map": rec.get("last_map"),
            "proof_directory": rec.get("proof_directory"),
            "project_health": rec.get("project_health"),
            "status": rec.get("status"),
            "connected_session_id": rec.get("connected_session_id"),
            "registered_at": rec.get("registered_at"),
            "last_connected_at": rec.get("last_connected_at"),
            "last_error": rec.get("last_error", ""),
        }


# ---------------------------------------------------------------------------
# Module-level default instance (composition root shares this).
# ---------------------------------------------------------------------------

_default_registry: Optional[ProjectRegistry] = None
_registry_lock = threading.Lock()


def get_default_registry() -> ProjectRegistry:
    global _default_registry
    with _registry_lock:
        if _default_registry is None:
            _default_registry = ProjectRegistry()
        return _default_registry


def list_projects() -> List[Dict[str, Any]]:
    return get_default_registry().list()


def register_project(uproject_path: str, **kwargs) -> Dict[str, Any]:
    return get_default_registry().register(uproject_path, **kwargs)


def connect_project(project_id: str, session_id: Optional[str] = None,
                    bridge_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return get_default_registry().connect(
        project_id, session_id=session_id, bridge_config=bridge_config)


def disconnect_project(project_id: str) -> Dict[str, Any]:
    return get_default_registry().disconnect(project_id)


def inspect_project(project_id: str) -> Dict[str, Any]:
    return get_default_registry().inspect(project_id)