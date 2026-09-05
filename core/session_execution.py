"""session_execution.py — per-session Unreal execution (Phases 3/4/7/9).

Every task belongs to exactly one session, and every session owns exactly
one Unreal bridge endpoint:

    client -> session -> project -> execution -> Unreal bridge -> proof

This module wraps the EXISTING canonical execution machinery (MissionEngine
+ UniversalPlanner + mission_policy + project_safety + editor_lease) with a
session-scoped dispatch chain. It never re-implements the step executor:
planning, dispatch, validation and acceptance all reuse the canonical
modules, so Planner Safety and READ_ONLY enforcement are preserved verbatim.

Dispatch chain (outermost to innermost):

    session identity guard   — fail closed: bridge down / wrong project /
                               editor PID changed blocks EVERY tool call
    policy_guarded_dispatch  — canonical READ_ONLY enforcement (existing)
    guard_dispatch           — ProjectMutationGuard (existing, session-bound)
    resource gate            — GPU_HEAVY tools respect the supervisor
    production dispatch      — existing registry + hard-timeout executor

Per-project mutation lease (core.editor_lease) serializes MUTATING work on
the SAME project while letting unrelated projects run concurrently.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core import app_config
from core.editor_lease import LeaseRegistry
from core.mission import MissionState, mission_response
from core.mission_policy import (
    MODE_READ_ONLY,
    classify_tool as policy_classify_tool,
    policy_snapshot,
    resolve_mission_mode,
)
from core.proof_store import ProofStore
from core.session_model import (
    BUSY,
    CRASHED,
    OFFLINE,
    READY,
    STARTING,
    BLOCKED,
    VALIDATING,
    SessionStore,
    SessionTask,
)
from core.universal_intent import expand_requirements, interpret_intent
from core.universal_planner import build_universal_planner

ROOT = Path(__file__).resolve().parents[1]
BRIDGE_BOOT_DIR = ROOT / "config" / "runtime" / "bridge_boot"

# Tools whose spec functions accept a `bridge`-ish injection (session-bound).
_BRIDGE_AWARE_TOOLS = {"inspect_project"}


def _normalized(path: Optional[str]) -> str:
    return str(path or "").replace("\\", "/").rstrip("/").lower()


# ---------------------------------------------------------------------------
# Bridge factory + session bridge resolution
# ---------------------------------------------------------------------------

def make_bridge(host: str, port: int, timeout: float = 30.0):
    """UnrealBridge bound to one session endpoint."""
    from tools.unreal.unreal_bridge import UnrealBridge
    return UnrealBridge(host=host, port=int(port), timeout=timeout)


def session_bridge_for(session_id: str,
                       store: Optional[SessionStore] = None) -> Any:
    """Resolve the live bridge for a session record (or None)."""
    store = store or SessionStore()
    session = store.get(session_id)
    if session is None or not session.bridge_port:
        return None
    return make_bridge(session.bridge_host, session.bridge_port)


def _identity_probe(bridge: Any) -> Dict[str, Any]:
    """Live editor identity via the bridge (project, PID, map, engine)."""
    if bridge is None:
        return {}
    try:
        result = bridge.execute_python(
            "import os\n"
            "project_path = str(unreal.Paths.get_project_file_path())"
            ".replace(chr(92), '/')  \n"
            "world = unreal.EditorLevelLibrary.get_editor_world()\n"
            "editor_subsystem = unreal.get_editor_subsystem("
            "unreal.UnrealEditorSubsystem)\n"
            "game_world = editor_subsystem.get_game_world() "
            "if editor_subsystem else None\n"
            "__bridge_result__ = {\n"
            "    'ok': bool(project_path),\n"
            "    'project_path': project_path,\n"
            "    'project_name': project_path.rsplit('/', 1)[-1]"
            ".rsplit('.', 1)[0],\n"
            "    'engine': unreal.SystemLibrary.get_engine_version(),\n"
            "    'editor_pid': os.getpid(),\n"
            "    'active_map': world.get_path_name() if world else '',\n"
            "    'pie_running': game_world is not None,\n"
            "}\n"
        )
        payload = (result.get("result")
                   if isinstance(result, dict) else None)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _process_alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=5)
        return str(pid) in out.stdout
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Per-session editor launch (unique bridge port)
# ---------------------------------------------------------------------------

def _bridge_bootstrap_source(listener: Path) -> str:
    """Minimal per-session bridge bootstrap. The listener reads its port from
    the UA_BRIDGE_PORT environment variable (see tools/unreal/ue_listener.py),
    so one bootstrap template serves every session port."""
    listener_path = str(listener.resolve()).replace("\\", "/")
    return f'''# >>> UA_SESSION_BRIDGE >>> (generated; per-session port)
import unreal as _ua_unreal
_ua_listener = r"{listener_path}"
_ua_state = {{"started": False, "error": None, "source": None}}

# Launched via -ExecutePythonScript: the EditorPythonExecuter quits the
# editor when the script finishes unless the keep-alive flag is set.
# ScriptName for UEditorPythonScriptingLibrary is "EditorPythonScripting".
_ua_keepalive = False
for _ua_cls in ("EditorPythonScripting", "EditorPythonScriptingLibrary"):
    try:
        _ua_mod = getattr(_ua_unreal, _ua_cls)
        _ua_mod.set_keep_python_script_alive(True)
        _ua_keepalive = True
        break
    except Exception:
        continue
if not _ua_keepalive:
    _ua_unreal.log_warning(
        "UA session bridge: keep-python-script-alive unavailable; "
        "the editor may quit after this script")


def _ua_set_keepalive(_delta=0.0):
    try:
        getattr(_ua_unreal, "EditorPythonScripting").set_keep_python_script_alive(True)
    except Exception:
        pass


try:
    _ua_unreal.register_slate_post_tick_callback(_ua_set_keepalive)
except Exception:
    pass


def _ua_start(_delta=0.0):
    if _ua_state["started"] and _ua_state["source"] is not None:
        return
    try:
        with open(_ua_listener, "r", encoding="utf-8-sig") as _f:
            _src = _f.read()
        _ns = {{"__name__": "__main__", "__file__": _ua_listener}}
        exec(compile(_src, _ua_listener, "exec"), _ns, _ns)
        _ua_state.update({{"started": True, "source": _ns}})
    except Exception as _exc:
        _ua_state["error"] = repr(_exc)
        _ua_unreal.log_error("UA session bridge startup failed: " + repr(_exc))


try:
    _ua_unreal.register_slate_post_tick_callback(_ua_start)
except Exception:
    _ua_start(0.0)
'''


def _editor_executable() -> Optional[Path]:
    try:
        from tools.unreal.project_manager import UNREAL_EDITOR
        if Path(UNREAL_EDITOR).exists():
            return Path(UNREAL_EDITOR)
    except Exception:
        pass
    try:
        for exe in app_config.unreal_editor_candidates():
            if exe and Path(exe).exists():
                return Path(exe)
    except Exception:
        pass
    return None


def launch_editor(uproject_path: str, port: int, *,
                  session_id: str,
                  wait_s: float = 600.0,
                  bootstrap_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Launch UnrealEditor for a project with a session-specific bridge port.

    The editor process is started with UA_BRIDGE_PORT set so the bridge
    listener binds the session's port. Identity (project path) is verified
    after boot before returning ok.
    """
    editor = _editor_executable()
    if editor is None:
        return {"ok": False,
                "error": "no Unreal Editor executable could be resolved"}
    project = Path(uproject_path).resolve()
    if not project.exists():
        return {"ok": False, "error": f"project not found: {project}"}

    boot_dir = Path(bootstrap_dir) if bootstrap_dir else BRIDGE_BOOT_DIR
    boot_dir.mkdir(parents=True, exist_ok=True)
    bootstrap = boot_dir / f"{session_id}.py"
    listener = Path(__file__).resolve().parents[1] / "tools" / "unreal" \
        / "ue_listener.py"
    bootstrap.write_text(
        _bridge_bootstrap_source(listener), encoding="utf-8")

    env = dict(os.environ)
    env["UA_BRIDGE_PORT"] = str(port)

    # Forward slashes: backslash-r etc. inside -ExecutePythonScript paths are
    # mangled by UE's command-line parsing (observed: config\runtime -> CR).
    script_arg = f'-ExecutePythonScript="{bootstrap.as_posix()}"'
    try:
        proc = subprocess.Popen(
            [str(editor), str(project), script_arg],
            cwd=str(project.parent),
            env=env,
        )
    except Exception as exc:
        return {"ok": False,
                "error": f"editor launch failed: {type(exc).__name__}: {exc}"}

    bridge = make_bridge("127.0.0.1", port, timeout=8)
    deadline = time.time() + wait_s
    last_error = "editor did not become ready"
    grace_until = time.time() + 20.0  # allow normal startup time
    while time.time() < deadline:
        identity = _identity_probe(bridge)
        if identity.get("ok") and _normalized(
                identity.get("project_path")) == _normalized(str(project)):
            return {
                "ok": True,
                "editor_pid": identity.get("editor_pid"),
                "identity": identity,
                "port": port,
                "launched": True,
                "process_pid": proc.pid,
            }
        if identity.get("ok"):
            last_error = (
                "bridge reached but identity mismatch: "
                f"{identity.get('project_path')}")
        elif time.time() > grace_until and not _process_alive(proc.pid):
            # Editor exited during boot (e.g. script failure). Fail fast
            # instead of polling a dead process for the full wait budget.
            return {"ok": False, "port": port, "process_pid": proc.pid,
                    "error": ("editor process exited during boot: "
                               + last_error)}
        time.sleep(2)

    return {"ok": False, "port": port, "process_pid": proc.pid,
            "error": (f"bridge did not verify on {port} for "
                      f"{project.name} within {int(wait_s)}s: {last_error}")}


# ---------------------------------------------------------------------------
# Session runner
# ---------------------------------------------------------------------------

class SessionRunner:
    """Runs session-scoped actions over the canonical execution machinery."""

    def __init__(
        self,
        store: Optional[SessionStore] = None,
        registry_builder: Optional[Callable[[Any], Dict[str, Any]]] = None,
        proof_store: Optional[ProofStore] = None,
        allocator: Any = None,
        leases: Optional[LeaseRegistry] = None,
        supervisor: Any = None,
        bridge_factory: Optional[Callable[[str, int, float], Any]] = None,
    ):
        self.store = store or SessionStore()
        self._registry_builder = registry_builder or _build_session_registry
        self.proof = proof_store or ProofStore()
        if allocator is None:
            from core.bridge_allocator import get_default_allocator
            allocator = get_default_allocator()
        self.allocator = allocator
        self.leases = leases or LeaseRegistry()
        if supervisor is None:
            from core.resource_supervisor import get_default_supervisor
            supervisor = get_default_supervisor()
        self.supervisor = supervisor
        self._bridge_factory = bridge_factory or make_bridge
        self._sweeper: Optional[threading.Thread] = None
        self._cancel_flags: Dict[str, bool] = {}
        self._cancel_lock = threading.Lock()
        self._hydrate_bindings()

    def _hydrate_bindings(self) -> None:
        """Re-claim allocator bindings for persisted live sessions after a
        backend restart, so the allocator view stays consistent with the
        session store (ports come from the session records; identity is
        re-verified at dispatch time regardless)."""
        for session in self.store.list():
            if session.status not in ("STARTING", "READY", "BUSY",
                                     "VALIDATING", "BLOCKED"):
                continue
            if not session.bridge_port:
                continue
            if self.allocator.binding_for(session.project_id) is not None:
                continue
            try:
                self.allocator.allocate(
                    session.project_id,
                    preferred=int(session.bridge_port),
                    force=True,
                )
            except Exception:
                pass

    def request_cancel(self, execution_id: str) -> None:
        with self._cancel_lock:
            self._cancel_flags[str(execution_id)] = True

    def _is_cancelled(self, execution_id: str) -> bool:
        with self._cancel_lock:
            return bool(self._cancel_flags.get(str(execution_id)))

    # -- lifecycle ------------------------------------------------------------
    def start(self) -> "SessionRunner":
        self.supervisor.start()
        if self._sweeper is None or not self._sweeper.is_alive():
            self._sweeper = threading.Thread(
                target=self._health_sweep, name="aivido-session-health",
                daemon=True)
            self._sweeper.start()
        return self

    def _health_sweep(self, interval: float = 15.0) -> None:
        while True:
            try:
                for session in self.store.list():
                    if session.status in ("STARTING", "READY", "BUSY",
                                          "VALIDATING", "BLOCKED"):
                        self.check_health(session.session_id)
            except Exception:
                pass
            time.sleep(interval)

    # -- bridge start / restart -------------------------------------------------
    def start_project(self, session, *, launch_if_needed: bool = True,
                      wait_s: float = 600.0) -> Dict[str, Any]:
        """Start (or reuse) the Unreal bridge for a session's project.

        Keyed by PROJECT: two sessions on the same project share one editor /
        bridge endpoint; unrelated projects get unique ports.
        """
        store = self.store
        store.set_status(session.session_id, STARTING,
                         error="starting project session")

        # 1) REUSE FIRST: a live bridge already serving this project is the
        #    cheapest correct outcome (no second editor, no port churn).
        #    Candidates: the session's known port, the allocator's existing
        #    binding for this project, and the canonical default bridge port
        #    (6766) — the legacy endpoint a running editor uses.
        candidates: List[int] = []
        if session.bridge_port:
            candidates.append(int(session.bridge_port))
        binding = self.allocator.binding_for(session.project_id)
        if binding is not None and binding not in candidates:
            candidates.append(int(binding))
        from core import app_config as _cfg
        default_port = int(getattr(_cfg, "BRIDGE_PORT_DEFAULT", 6766))
        if default_port not in candidates:
            candidates.append(default_port)
        for candidate in candidates:
            bridge = self._bridge_factory("127.0.0.1", candidate, 8)
            identity = _identity_probe(bridge)
            if identity.get("ok") and _normalized(
                    identity.get("project_path")) == _normalized(
                    session.project_path):
                alloc = self.allocator.allocate(
                    session.project_id, preferred=candidate, force=True)
                if alloc.get("ok"):
                    return self._attach_identity(
                        session, candidate, identity, launched_by="reuse")

        # 2) Fresh endpoint: allocate a collision-free port.
        alloc = self.allocator.allocate(session.project_id)
        if not alloc.get("ok"):
            store.set_status(session.session_id, CRASHED,
                             error=alloc.get("error", "port allocation failed"))
            return {"ok": False, "error": alloc.get("error")}
        port = alloc["port"]

        # 3) Launch a fresh editor for this project on the session port.
        if not launch_if_needed:
            store.set_status(session.session_id, OFFLINE,
                             error="project not running and launch disabled")
            return {"ok": False, "code": "NOT_RUNNING",
                    "error": "project editor not running; launch disabled",
                    "port": port}

        result = launch_editor(session.project_path, port,
                               session_id=session.session_id,
                               wait_s=wait_s)
        if not result.get("ok"):
            store.set_status(session.session_id, CRASHED,
                             error=result.get("error", "launch failed"))
            return {"ok": False, "error": result.get("error"), "port": port,
                    "process_pid": result.get("process_pid")}

        identity = result.get("identity") or {}
        return self._attach_identity(session, port, identity,
                                     launched_by="launch")

    def _attach_identity(self, session, port, identity, *,
                         launched_by: str) -> Dict[str, Any]:
        def _apply(s: Any) -> None:
            s.bridge_host = "127.0.0.1"
            s.bridge_port = port
            s.unreal_pid = identity.get("editor_pid") or s.unreal_pid
            s.engine_version = str(identity.get("engine") or "") \
                or s.engine_version
            s.active_map = str(identity.get("active_map") or "") \
                or s.active_map
            s.launched_by = launched_by
            s.status = READY
            s.last_error = ""
            s.resource_state = {"bridge_ok": True}
        self.store.update(session.session_id, _apply)
        return {
            "ok": True,
            "session_id": session.session_id,
            "project_id": session.project_id,
            "bridge": f"127.0.0.1:{port}",
            "unreal_pid": identity.get("editor_pid"),
            "active_map": identity.get("active_map"),
            "engine_version": identity.get("engine"),
            "launched_by": launched_by,
            "status": READY,
        }

    def restart_project(self, session_id: str,
                        wait_s: float = 600.0) -> Dict[str, Any]:
        """Phase 9: reconnect a live bridge, or relaunch the project editor.
        Only this session is affected — other sessions are untouched."""
        store = self.store
        session = store.require(session_id)

        # Try a pure reconnect first (bridge alive, identity matches).
        if session.bridge_port:
            bridge = self._bridge_factory(
                session.bridge_host, session.bridge_port, 6)
            identity = _identity_probe(bridge)
            if identity.get("ok") and _normalized(
                    identity.get("project_path")) == _normalized(
                    session.project_path):
                return self._attach_identity(session, session.bridge_port,
                                             identity, launched_by="reconnect")

        # Release the stale binding so the allocator can pick a free port.
        self.allocator.release(session.project_id)
        return self.start_project(session, launch_if_needed=True,
                                  wait_s=wait_s)

    def disconnect(self, session_id: str) -> Dict[str, Any]:
        store = self.store
        session = store.require(session_id)
        store.set_status(session_id, OFFLINE, error="disconnected by client")
        self.allocator.release(session.project_id)
        try:
            from core.project_registry import get_default_registry
            reg = get_default_registry()
            rec = reg.get(session.project_id)
            if rec and rec.get("connected_session_id") == session_id:
                reg.disconnect(session.project_id)
        except Exception:
            pass
        return {"ok": True, "session_id": session_id, "status": OFFLINE}

    # -- health / crash detection ----------------------------------------------
    def check_health(self, session_id: str) -> Dict[str, Any]:
        store = self.store
        session = store.get(session_id)
        if session is None:
            return {"ok": False, "error": "unknown session"}
        if session.status == OFFLINE:
            return {"ok": True, "status": OFFLINE}
        bridge = None
        if session.bridge_port:
            bridge = self._bridge_factory(
                session.bridge_host, session.bridge_port, 5)
        identity = _identity_probe(bridge)
        if identity.get("ok") and _normalized(
                identity.get("project_path")) == _normalized(
                session.project_path):
            pid_ok = (session.unreal_pid is None
                      or identity.get("editor_pid") is None
                      or identity.get("editor_pid") == session.unreal_pid)
            if pid_ok:
                store.update(session_id, lambda s: (
                    setattr(s, "status", READY if s.status == CRASHED
                            else s.status),
                    setattr(s, "last_error", ""),
                    setattr(s, "active_map",
                            str(identity.get("active_map") or "")
                            or s.active_map),
                ) and None)
                return {"ok": True, "status": "READY", "identity": identity}
        # Bridge down or identity/PID mismatch -> this session only crashes.
        detail = (
            f"bridge {session.bridge_host}:{session.bridge_port} "
            "unreachable or identity mismatch"
            if session.bridge_port else "no bridge endpoint bound")
        store.set_status(session_id, CRASHED, error=detail)
        return {"ok": False, "status": CRASHED, "error": detail}

    # -- prompt execution --------------------------------------------------------
    def run_prompt(
        self,
        session_id: str,
        prompt: str,
        *,
        read_only: Optional[bool] = None,
        mode: Optional[str] = None,
        execution_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute one prompt in the session context (canonical machinery)."""
        store = self.store
        try:
            session = store.require(session_id)
        except KeyError:
            return {
                "ok": False,
                "code": "SESSION_NOT_FOUND",
                "error": f"unknown session {session_id}; fail-closed: "
                         "refusing to run an un-scoped action",
            }

        if session.status == CRASHED:
            return {
                "ok": False,
                "code": "SESSION_CRASHED",
                "session_id": session_id,
                "error": (
                    "session is CRASHED; restart the project session before "
                    "dispatching work (POST /api/sessions/{id}/restart)"),
            }
        if not session.bridge_port:
            return {
                "ok": False,
                "code": "SESSION_NOT_STARTED",
                "session_id": session_id,
                "error": (
                    "session bridge not started; call start first "
                    "(POST /api/sessions/{id}/start)"),
            }

        prompt = str(prompt or "").strip()
        if not prompt:
            return {"ok": False, "error": "prompt cannot be empty"}

        execution_id = execution_id or f"exec_{uuid.uuid4().hex[:10]}"

        # -- canonical execution mode (READ_ONLY / MUTATING) -------------------
        read_only_flag = resolve_mission_mode(
            prompt, explicit_read_only=read_only,
            request_mode=mode) == MODE_READ_ONLY

        # -- resource policy gate (coarse, pre-plan) ----------------------------
        from core.resource_supervisor import (
            QUEUED_RESOURCE, RUNNING, THROTTLED, classify_prompt)
        resource_kind = classify_prompt(prompt)
        decision = self.supervisor.gate(resource_kind)
        if decision != RUNNING:
            task = SessionTask(
                execution_id=execution_id, prompt=prompt,
                mode=mode or "execute", read_only=read_only_flag,
                status="queued_resource", resource_decision=decision)
            store.update(session_id, lambda s: (
                s.enqueue(task), setattr(s, "resource_state", {
                    "last_decision": decision,
                    "kind": resource_kind,
                })) and None)
            return {
                "ok": True,
                "accepted": False,
                "execution_id": execution_id,
                "status": decision,
                "resource_decision": decision,
                "message": (
                    "task queued by resource supervisor (GPU headroom / "
                    "heavy-task budget); it will run when the GPU is free"),
            }

        # -- per-project lease (mutating exclusive; read-only watchers) --------
        lease = self.leases.acquire(
            session.project_path,
            owner_id=session.session_id,
            task_id=execution_id,
            read_only=read_only_flag,
        )
        if not lease.get("ok"):
            conflict = lease.get("conflict") or {}
            task = SessionTask(
                execution_id=execution_id, prompt=prompt,
                mode=mode or "execute", read_only=read_only_flag,
                status="queued", resource_decision="RUNNING")
            store.update(session_id, lambda s: s.enqueue(task))
            return {
                "ok": False,
                "code": "PROJECT_BUSY",
                "execution_id": execution_id,
                "error": (
                    "another task holds this project's mutation lease; "
                    "same-project mutations serialize"),
                "conflict": conflict,
                "lease": lease,
            }

        try:
            return self._run_locked(
                session, prompt, execution_id=execution_id,
                read_only=read_only_flag, mode=mode or "execute",
                lease_owner=session.session_id,
                resource_kind=resource_kind,
                decision=decision,
            )
        finally:
            try:
                self.leases.release(session.project_path,
                                    session.session_id)
            except Exception:
                pass

    def _run_locked(
        self, session, prompt: str, *, execution_id: str,
        read_only: bool, mode: str, lease_owner: str,
        resource_kind: str, decision: str,
    ) -> Dict[str, Any]:
        store = self.store
        task = SessionTask(
            execution_id=execution_id, prompt=prompt, mode=mode,
            read_only=read_only, status="running",
            resource_decision=decision)
        store.update(session.session_id, lambda s: (
            s.enqueue(task),
            setattr(s, "current_execution_id", execution_id),
            setattr(s, "status", BUSY),
            setattr(s, "resource_state", {"kind": resource_kind,
                                          "decision": decision}),
        ) and None)

        bridge = self._bridge_factory(
            session.bridge_host, session.bridge_port, 30)

        # -- fail-closed identity verification BEFORE any work -----------------
        identity = _identity_probe(bridge)
        if not identity.get("ok") or _normalized(
                identity.get("project_path")) != _normalized(
                session.project_path):
            store.set_status(session.session_id, CRASHED,
                             error="bridge unreachable or wrong project at "
                                   "dispatch time")
            store.finish_execution(
                session.session_id, execution_id, "BLOCKED",
                why="fail-closed session identity check failed before any "
                    "tool ran", status=CRASHED)
            return {
                "ok": False,
                "code": "SESSION_IDENTITY_FAILED",
                "execution_id": execution_id,
                "error": (
                    "refusing to dispatch: live editor identity does not "
                    f"match session {session.session_id} "
                    f"(expected {session.project_path})"),
            }

        # -- per-session registry (bridge bound to THIS session) ---------------
        registry = self._registry_builder(bridge)

        # -- plan through the canonical deterministic planner ------------------
        state = MissionState(
            mission_id=f"mission_{execution_id}",
            prompt=prompt,
        )
        state.started_at = time.time()
        intent = interpret_intent(prompt)
        requirements = expand_requirements(intent)
        state.intent = intent.to_dict()
        state.requirements = requirements.to_dict()
        state.read_only = read_only
        # Explicit request mode wins (contract: force chat|plan|execute).
        if mode in ("chat", "plan", "execute"):
            intent.mode = mode
        planner = build_universal_planner(registry)
        mission_plan = planner.build_plan(
            intent, requirements,
            {"project_path": session.project_path,
             "project_name": session.project_name})
        state.plan = mission_plan.to_dict()

        # -- canonical plan gate (READ_ONLY plan violations -> PLAN_REJECTED) --
        state.policy = policy_snapshot(state)
        from core.mission_policy import plan_violations
        violations = plan_violations(read_only, state.plan.get("steps") or [])
        if violations:
            blocked_tools = sorted(
                {str(v.get("tool") or "") for v in violations})
            state.status = "blocked"
            state.verdict = "PLAN_REJECTED"
            state.why = (
                "Plan rejected by read-only execution policy; blocked tools: "
                + ", ".join(blocked_tools)
                + ". Read-only missions never execute non-read-only tools; "
                "zero steps ran.")
            state.finished_at = time.time()
            store.finish_execution(
                session.session_id, execution_id, "BLOCKED",
                why=state.why, status=BLOCKED)
            store.set_status(session.session_id, BLOCKED,
                             error=state.why)
            response = mission_response(state)
            response["execution_id"] = execution_id
            return {"ok": False, "code": "PLAN_REJECTED",
                    "execution_id": execution_id,
                    "response": response, "status": "BLOCKED"}

        # -- dispatch chain -----------------------------------------------------
        # Wrap order (outermost -> innermost):
        #   READ_ONLY policy -> resource gate -> project mutation guard
        #   -> session identity guard -> production dispatch
        # So a policy or resource refusal never touches the bridge, while
        # every tool call that does reach dispatch is identity-verified.
        from core.project_safety import ProjectMutationGuard, guard_dispatch
        from app.unreal_coder_api import policy_guarded_dispatch
        from core.resource_supervisor import RUNNING as R, classify_tools

        production = _production_dispatch(registry, bridge=bridge)

        def identity_guard(step: Dict[str, Any]) -> Dict[str, Any]:
            live = _identity_probe(bridge)
            if not live.get("ok") or _normalized(
                    live.get("project_path")) != _normalized(
                    session.project_path):
                store.set_status(session.session_id, CRASHED,
                                 error="bridge identity lost mid-execution")
                return {
                    "ok": False,
                    "code": "SESSION_IDENTITY_FAILED",
                    "tool": str(step.get("preferred_tool") or ""),
                    "error": (
                        "fail-closed: session bridge identity lost; "
                        "refusing tool dispatch"),
                }
            pid_ok = (session.unreal_pid is None
                      or live.get("editor_pid") is None
                      or live.get("editor_pid") == session.unreal_pid)
            if not pid_ok:
                store.set_status(session.session_id, CRASHED,
                                 error="editor PID changed mid-execution")
                return {
                    "ok": False,
                    "code": "EDITOR_RESTARTED",
                    "tool": str(step.get("preferred_tool") or ""),
                    "error": (
                        "fail-closed: editor PID changed mid-execution; "
                        "session marked CRASHED"),
                }
            return production(step)

        guard = ProjectMutationGuard(
            bridge=bridge,
            expected_uproject=session.project_path)

        def resource_gated(step: Dict[str, Any]) -> Dict[str, Any]:
            tool = str(step.get("preferred_tool") or "")
            kind = classify_tools([tool])
            if kind == "GPU_HEAVY":
                gate = self.supervisor.gate("GPU_HEAVY")
                if gate != R:
                    return {
                        "ok": False,
                        "throttled": True,
                        "resource_decision": gate,
                        "tool": tool,
                        "error": (
                            f"RESOURCE_{gate}: GPU-heavy tool '{tool}' held "
                            "by the resource supervisor"),
                    }
            return guarded_inner(step)

        guarded_mutations = guard_dispatch(identity_guard, guard)

        def guarded_inner(step: Dict[str, Any]) -> Dict[str, Any]:
            return guarded_mutations(step)

        policy_chain = policy_guarded_dispatch(
            read_only, resource_gated)

        # Client cancel: stops at the next step boundary.
        def cancel_checked(step: Dict[str, Any]) -> Dict[str, Any]:
            if self._is_cancelled(execution_id):
                return {
                    "ok": False,
                    "code": "CANCELLED",
                    "cancelled": True,
                    "tool": str(step.get("preferred_tool") or ""),
                    "error": "MISSION_CANCELLED_BY_CLIENT",
                }
            return policy_chain(step)

        guarded = cancel_checked

        # -- engine (canonical MissionEngine with session dispatch) ------------
        from core.mission import MissionEngine
        from core.capability_registry import build_capability_registry
        capabilities = build_capability_registry(registry)

        from app.unreal_coder_api import _default_visual_adapters
        run_capture, run_evaluate, run_repair = (
            _default_visual_adapters(registry))
        if read_only:
            run_repair = None

        engine = MissionEngine(
            tool_registry=registry,
            capabilities=capabilities,
            dispatch=guarded,
            capture=run_capture,
            evaluate=run_evaluate,
            repair=run_repair,
        )
        state = engine.run(state)

        # -- client-cancel finalization (never a fake SUCCESS) ----------------
        if self._is_cancelled(execution_id):
            state.status = "blocked"
            state.verdict = "CANCELLED"
            state.why = "Mission cancelled by client request; stopped at " \
                        "the next step boundary."
            state.finished_at = time.time()
            state.save()

        # -- refresh identity + record proof -----------------------------------
        live = _identity_probe(bridge)
        if live.get("ok"):
            store.update(session.session_id, lambda s: (
                setattr(s, "active_map",
                        str(live.get("active_map") or "") or s.active_map),
                setattr(s, "engine_version",
                        str(live.get("engine") or "") or s.engine_version),
                setattr(s, "unreal_pid",
                        live.get("editor_pid") or s.unreal_pid),
            ) and None)

        proof_records = self._record_proof(
            session, execution_id, state, live)

        # -- session status mapping ---------------------------------------------
        if state.status == "blocked":
            session_status = BLOCKED if state.verdict != "CANCELLED" \
                else READY
        elif state.status in ("complete", "failed"):
            session_status = READY
        else:  # repairing / validating leftovers
            session_status = VALIDATING
        store.finish_execution(
            session.session_id, execution_id,
            state.verdict or "FAIL", why=state.why,
            proof=[p.get("url") for p in proof_records],
            status=session_status)

        response = mission_response(state)
        response["execution_id"] = execution_id
        response["session_id"] = session.session_id
        response["project_id"] = session.project_id
        response["proof"] = proof_records
        return {"ok": True, "execution_id": execution_id,
                "session_id": session.session_id,
                "project_id": session.project_id,
                "verdict": state.verdict, "status": state.status,
                "why": state.why, "response": response,
                "proof": proof_records}

    # -- proof isolation ----------------------------------------------------------
    def _record_proof(self, session, execution_id: str, state, live) -> List[Dict]:
        """Copy session captures into the isolated proof tree + metadata."""
        sources: List[str] = []
        # 1) capture tool outputs inside the mission step results
        for sid in state.completed_step_ids:
            result = state.step_results.get(sid) or {}
            path = (result.get("path") or result.get("resource_path"))
            if path and Path(str(path)).is_file():
                sources.append(str(path))
            inner = result.get("result")
            if isinstance(inner, dict):
                p2 = inner.get("path") or inner.get("resource_path")
                if p2 and Path(str(p2)).is_file():
                    sources.append(str(p2))
        # 2) the project's own capture dir (viewport_latest etc.)
        if session.project_path:
            saved = (Path(session.project_path).resolve().parent
                     / "Saved" / "UnrealAgent")
            if saved.is_dir():
                for pattern in ("viewport_latest.png",
                                "pie_viewport_latest.png"):
                    f = saved / pattern
                    if f.is_file() and f.stat().st_size > 0:
                        sources.append(str(f))
        if not sources:
            return []
        result = self.proof.record(
            session.session_id, execution_id, sources,
            project_id=session.project_id,
            unreal_pid=session.unreal_pid,
            bridge_host=session.bridge_host,
            bridge_port=session.bridge_port,
            engine_version=session.engine_version,
            active_map=session.active_map,
        )
        return result.get("files", []) if result.get("ok") else []


# ---------------------------------------------------------------------------
# Per-session registry + production dispatch
# ---------------------------------------------------------------------------

def _build_session_registry(bridge: Any) -> Dict[str, Any]:
    """Clone the canonical tool registry with the bridge bound to ONE session.

    Reuses the canonical build_registry (same tool set, same specs); only the
    UnrealBridge instance differs. This is not a parallel executor — it is the
    same registry machinery pointed at a different editor endpoint.
    """
    from core import orchestrator
    from core.tool_registry import build_registry
    return build_registry(
        orchestrator.discover_projects,
        orchestrator.inspect_project,
        orchestrator.open_project,
        orchestrator.create_project,
        orchestrator.read_text_file,
        orchestrator.write_text_file,
        orchestrator.run_powershell,
        orchestrator.unreal_status,
        bridge=bridge,
    )


def _production_dispatch(registry: Dict[str, Any],
                         bridge: Any = None) -> Callable:
    """Existing-style step dispatcher: registry lookup + hard-timeout call.

    Tools that accept a live-bridge injection (e.g. inspect_project) are
    pinned to the SESSION bridge so a read-only inspect can never fall back
    to the global fixed bridge (127.0.0.1:6766) of another session.
    """
    def dispatch(step: Dict[str, Any]) -> Dict[str, Any]:
        tool = str(step.get("preferred_tool") or "")
        spec = registry.get(tool)
        if spec is None:
            return {"ok": False, "error": f"Unknown tool {tool}"}
        args = dict(step.get("parameters") or {})
        if tool in _BRIDGE_AWARE_TOOLS and bridge is not None:
            args.setdefault("_bridge", bridge)
        from app.api import call_tool_hard_timeout, _tool_success
        try:
            raw = call_tool_hard_timeout(spec, args)
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return {"ok": _tool_success(raw), "result": raw, "tool": tool}
    return dispatch


# ---------------------------------------------------------------------------
# Default runner singleton
# ---------------------------------------------------------------------------

# Results of background (async) session prompts, keyed by execution_id.
_background_results: Dict[str, Any] = {}
_background_lock = threading.Lock()


def store_background_result(execution_id: str, result: Dict[str, Any]) -> None:
    with _background_lock:
        _background_results[execution_id] = result


_default_runner: Optional[SessionRunner] = None
_runner_lock = threading.Lock()


def get_default_runner() -> SessionRunner:
    global _default_runner
    with _runner_lock:
        if _default_runner is None:
            _default_runner = SessionRunner().start()
        return _default_runner


def session_execution_status(session_id: str,
                             store: Optional[SessionStore] = None) -> Dict[str, Any]:
    """Derived status for polling: combines the session record with the
    mission checkpoint so VALIDATING is reported truthfully.

    `store` may be injected (the API layer passes its own SessionStore so
    the same store instance the caller uses is consulted)."""
    store = store or SessionStore()
    session = store.get(session_id)
    if session is None:
        return {"ok": False, "error": f"unknown session {session_id}"}
    out = session.summary()
    eid = session.current_execution_id
    if eid:
        checkpoint = MissionState.load(f"mission_{eid}")
        if checkpoint is not None:
            out["mission_status"] = checkpoint.status
            out["mission_verdict"] = checkpoint.verdict
            out["mission_steps_completed"] = len(
                checkpoint.completed_step_ids)
            if checkpoint.status == "validating":
                out["status"] = VALIDATING
            elif checkpoint.status == "executing":
                out["status"] = BUSY
    return {"ok": True, "session": out}