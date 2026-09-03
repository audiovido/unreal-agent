"""project_safety.py — UNREAL CODER real multi-project safety (Phase C).

Every live session carries a verified identity:

    project name, uproject path, editor PID, UE version, bridge endpoint,
    session identity, active map, PIE state

Before EVERY mutation the session is re-validated against the live editor.
A stale bridge (editor restarted -> new PID), a wrong project, or a changed
active map blocks the mutation with a structured error instead of mutating
the wrong target. Cross-project mutation is a RELEASE BLOCKER.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

BRIDGE_PORT = 6766


def _normalized(path: Optional[str]) -> str:
    return str(path or "").replace("\\", "/").rstrip("/").lower()


@dataclass
class SessionIdentity:
    """Verified identity of one live editor session."""

    session_id: str
    project_name: str = ""
    uproject_path: str = ""
    engine_version: str = ""
    editor_pid: Optional[int] = None
    bridge_host: str = "127.0.0.1"
    bridge_port: int = BRIDGE_PORT
    active_map: str = ""
    pie_running: bool = False
    verified_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "project_name": self.project_name,
            "uproject_path": self.uproject_path,
            "engine_version": self.engine_version,
            "editor_pid": self.editor_pid,
            "bridge": f"{self.bridge_host}:{self.bridge_port}",
            "active_map": self.active_map,
            "pie_running": self.pie_running,
            "verified_at": self.verified_at,
        }

    def matches_project(self, uproject_path: Optional[str] = None,
                        project_name: Optional[str] = None) -> bool:
        if uproject_path:
            return _normalized(self.uproject_path) == _normalized(uproject_path)
        if project_name:
            return self.project_name.lower() == project_name.lower()
        return True


@dataclass
class GuardVerdict:
    ok: bool
    code: str = "OK"
    detail: str = ""
    live: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "code": self.code, "detail": self.detail,
                "live": dict(self.live)}


class ProjectMutationGuard:
    """Validates the live editor session before any mutating tool call."""

    def __init__(self, bridge: Any = None,
                 expected_uproject: Optional[str] = None,
                 expected_project_name: Optional[str] = None):
        self.bridge = bridge
        self.expected_uproject = expected_uproject
        self.expected_project_name = expected_project_name
        self.identity: Optional[SessionIdentity] = None
        self.history: List[Dict[str, Any]] = []

    # -- identity capture ----------------------------------------------------
    def capture_identity(self) -> SessionIdentity:
        """Read the live editor identity (PID, version, map, PIE)."""
        code = r"""
import os
project_path = str(unreal.Paths.get_project_file_path()).replace(chr(92), "/")
world = unreal.EditorLevelLibrary.get_editor_world()
editor_subsystem = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
game_world = editor_subsystem.get_game_world() if editor_subsystem else None
__bridge_result__ = {
    "ok": bool(project_path),
    "project_path": project_path,
    "project_name": project_path.rsplit("/", 1)[-1].rsplit(".", 1)[0],
    "engine": unreal.SystemLibrary.get_engine_version(),
    "editor_pid": os.getpid(),
    "active_map": world.get_path_name() if world else "",
    "pie_running": game_world is not None,
}
"""
        live: Dict[str, Any] = {}
        if self.bridge is not None:
            try:
                result = self.bridge.execute_python(code)
                payload = (result.get("result")
                           if isinstance(result, dict) else {})
                if isinstance(payload, dict) and payload.get("ok"):
                    live = payload
            except Exception:
                # Bridge transport failure == editor unreachable. The empty
                # live dict below yields BRIDGE_DOWN at validation time.
                live = {}
        now = time.time()
        identity = SessionIdentity(
            session_id=f"sess_{uuid.uuid4().hex[:10]}",
            project_name=str(live.get("project_name") or ""),
            uproject_path=str(live.get("project_path") or ""),
            engine_version=str(live.get("engine") or ""),
            editor_pid=live.get("editor_pid"),
            bridge_host=getattr(self.bridge, "host", "127.0.0.1"),
            bridge_port=int(getattr(self.bridge, "port", BRIDGE_PORT)),
            active_map=str(live.get("active_map") or ""),
            pie_running=bool(live.get("pie_running")),
            verified_at=now,
        )
        self.identity = identity
        return identity

    # -- validation ------------------------------------------------------------
    def validate_mutation(
        self,
        expected_uproject: Optional[str] = None,
        expected_project_name: Optional[str] = None,
        allow_pie: bool = False,
        allow_map_change: bool = False,
    ) -> GuardVerdict:
        """Re-read live identity and enforce the safety contract.

        Blocks: bridge down, wrong project, editor restart (PID change),
        map change mid-mission (unless allowed), PIE mutation (unless allowed).
        """
        previous = self.identity
        live = self.capture_identity()
        record: Dict[str, Any] = {
            "at": time.time(),
            "live": live.to_dict(),
        }

        if not live.uproject_path:
            self.history.append(record)
            return GuardVerdict(
                False, "BRIDGE_DOWN",
                "live editor session not reachable; refusing to mutate",
                live.to_dict())

        wanted_path = expected_uproject or self.expected_uproject
        wanted_name = expected_project_name or self.expected_project_name
        if wanted_path and not live.matches_project(uproject_path=wanted_path):
            record["verdict"] = "WRONG_PROJECT"
            self.history.append(record)
            return GuardVerdict(
                False, "WRONG_PROJECT",
                f"live editor has {live.uproject_path}, mission targets "
                f"{wanted_path}; refusing cross-project mutation",
                live.to_dict())
        if wanted_name and not live.matches_project(project_name=wanted_name):
            record["verdict"] = "WRONG_PROJECT"
            self.history.append(record)
            return GuardVerdict(
                False, "WRONG_PROJECT",
                f"live editor has project '{live.project_name}', mission "
                f"targets '{wanted_name}'",
                live.to_dict())

        if previous is not None:
            if previous.editor_pid and live.editor_pid and \
                    previous.editor_pid != live.editor_pid:
                record["verdict"] = "EDITOR_RESTARTED"
                self.history.append(record)
                return GuardVerdict(
                    False, "EDITOR_RESTARTED",
                    f"editor PID changed {previous.editor_pid} -> "
                    f"{live.editor_pid}; session stale; re-ground before "
                    "mutating",
                    live.to_dict())
            if not allow_map_change and previous.active_map and \
                    live.active_map and previous.active_map != live.active_map:
                record["verdict"] = "MAP_CHANGED"
                self.history.append(record)
                return GuardVerdict(
                    False, "MAP_CHANGED",
                    f"active map changed {previous.active_map} -> "
                    f"{live.active_map} mid-mission",
                    live.to_dict())
        if live.pie_running and not allow_pie:
            record["verdict"] = "PIE_ACTIVE"
            self.history.append(record)
            return GuardVerdict(
                False, "PIE_ACTIVE",
                "Play In Editor is running; editor-world mutation blocked",
                live.to_dict())

        record["verdict"] = "OK"
        self.history.append(record)
        return GuardVerdict(True, "OK", "session identity verified",
                            live.to_dict())


# ---------------------------------------------------------------------------
# Convenience: attach the guard to a MissionEngine-style dispatch callable
# ---------------------------------------------------------------------------

MUTATING_TOOLS = {
    "spawn_actor", "move_actor", "rotate_actor", "scale_actor",
    "delete_actor", "delete_asset", "save_level", "create_default_level",
    "open_map", "import_asset", "import_asset_fbx", "import_asset_gltf",
    "import_blender_output", "spawn_imported_asset", "spawn_blender_output",
    "create_blueprint", "compile_blueprint", "save_blueprint",
    "add_blueprint_variable", "set_blueprint_variable_default",
    "add_blueprint_component", "create_umg_widget", "create_widget_blueprint",
    "add_text_widget", "add_button", "bind_button_event",
    "add_widget_to_viewport", "set_widget_text", "set_ui_state",
    "spawn_character", "set_character_transform", "assign_animation",
    "install_character_assets", "start_pie", "stop_pie",
    "graph_add_event_override", "graph_add_call_function",
    "graph_connect_pins", "graph_set_pin_default", "graph_delete_node",
    "graph_compile_save", "graph_build_beginplay_print",
    "write_text_file", "run_powershell",
}


def guard_dispatch(dispatch: Any, guard: ProjectMutationGuard,
                   **guard_kwargs) -> Any:
    """Wrap a mission dispatch callable so every mutating step re-validates
    the live session first. Read-only tools pass through."""
    def wrapped(step: Dict[str, Any]) -> Dict[str, Any]:
        tool = str(step.get("preferred_tool") or "")
        if tool in MUTATING_TOOLS:
            verdict = guard.validate_mutation(**guard_kwargs)
            if not verdict.ok:
                return {"ok": False, "error": f"{verdict.code}: {verdict.detail}",
                        "guard": verdict.to_dict()}
        return dispatch(step)
    return wrapped


def active_session_identity(bridge: Any = None) -> Optional[SessionIdentity]:
    """Capture the current live session identity (or None when offline)."""
    try:
        guard = ProjectMutationGuard(bridge=bridge)
        identity = guard.capture_identity()
        return identity if identity.uproject_path else None
    except Exception:
        return None
