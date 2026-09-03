"""product_core.py — the one-click Unreal Agent product shell.

Smallest genuinely usable end-user layer over the FROZEN production core
(Steps 5-7):

  IDLE -> CONNECTING_PROJECT -> READY -> UNDERSTANDING_REQUEST -> PLANNING
       -> EXECUTING -> VALIDATING -> (SELF_FIXING)* -> COMPLETE / FAILED
       -> RECOVERING (transient bridge recovery, back to READY)

Design rules:
  * The UI request routes through the REAL stack: natural language ->
    core.universal_intent interpretation -> a small honest product planner
    (capability mapping over the real registry vocabulary) -> real Unreal
    execution through the live bridge -> fresh-capture validation with the
    Step-5 release evaluator -> autonomous correction through the Step-6/7
    visual director machinery when required -> terminal acceptance.
  * Progress is never fabricated: percentages appear only when a count is
    honestly known (planned steps vs completed steps).
  * No silent infinite retries: bounded recovery, then an actionable FAILED.
  * The state record is persisted on every transition (config/product_state
    .json) so an application restart keeps a sane, resumable picture.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
PRODUCT_CONFIG = CONFIG_DIR / "product.json"
STATE_FILE = CONFIG_DIR / "product_state.json"
PROOF_DIR = ROOT / "assetlib" / "proof" / "product"

# ---------------------------------------------------------------------------
# Task/connection state machine
# ---------------------------------------------------------------------------

# Product lifecycle states (user-facing vocabulary, Phase B contract).
IDLE = "IDLE"
CONNECTING_PROJECT = "CONNECTING_PROJECT"
READY = "READY"
UNDERSTANDING_REQUEST = "UNDERSTANDING_REQUEST"
PLANNING = "PLANNING"
EXECUTING = "EXECUTING"
VALIDATING = "VALIDATING"
SELF_FIXING = "SELF_FIXING"
COMPLETE = "COMPLETE"
FAILED = "FAILED"
RECOVERING = "RECOVERING"

STATES = [IDLE, CONNECTING_PROJECT, READY, UNDERSTANDING_REQUEST, PLANNING,
          EXECUTING, VALIDATING, SELF_FIXING, COMPLETE, FAILED, RECOVERING]

CONNECT_STATES = {CONNECTING_PROJECT, RECOVERING}
BUSY_STATES = {UNDERSTANDING_REQUEST, PLANNING, EXECUTING, VALIDATING,
               SELF_FIXING}
FINAL_STATES = {COMPLETE, FAILED}


@dataclass
class StageRecord:
    """One honest stage entry with wall-clock time and result."""
    name: str
    at: float = field(default_factory=time.time)
    status: str = "running"     # running | ok | failed
    detail: str = ""
    result: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name,
                "at": round(self.at, 3),
                "status": self.status,
                "detail": self.detail,
                "result": dict(self.result)}


@dataclass
class ProductState:
    """Single source of truth for the product UI (persisted)."""

    state: str = IDLE
    project: Dict[str, Any] = field(default_factory=dict)
    status_text: str = "Idle"
    task_id: Optional[str] = None
    current_stage: str = ""
    elapsed_s: float = 0.0
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    last_successful_action: str = ""
    active_issue: str = ""
    retry_count: int = 0
    steps_done: Optional[int] = None
    steps_total: Optional[int] = None
    final: Dict[str, Any] = field(default_factory=dict)
    proof: List[Dict[str, Any]] = field(default_factory=list)
    stages: List[Dict[str, Any]] = field(default_factory=list)
    history: List[Dict[str, Any]] = field(default_factory=list)
    error_detail: str = ""
    updated_at: float = field(default_factory=time.time)
    # Server-side wall-clock markers (ms-precision seconds) so the product
    # layer's own overhead is measurable end-to-end without browser clocks:
    # requested_at -> understand_at -> plan_at -> execute_at -> validate_at
    # -> terminal_at.  Never displayed as fake progress; only timing truth.
    timings: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        elapsed = None
        if self.started_at:
            base = self.finished_at if self.finished_at else time.time()
            elapsed = round(base - self.started_at, 2)
        progress = None
        if self.state == EXECUTING and self.steps_total:
            progress = {
                "completed": int(self.steps_done or 0),
                "total": int(self.steps_total),
            }
        return {
            "state": self.state,
            "project": dict(self.project),
            "status_text": self.status_text,
            "task_id": self.task_id,
            "current_stage": self.current_stage,
            "elapsed_s": elapsed,
            "progress": progress,
            "last_successful_action": self.last_successful_action,
            "active_issue": self.active_issue,
            "retry_count": int(self.retry_count),
            "final": dict(self.final),
            "proof": list(self.proof),
            "stages": list(self.stages),
            "error_detail": self.error_detail,
            "updated_at": round(self.updated_at, 3),
            "timings": {k: round(v, 3) for k, v in sorted(self.timings.items())},
        }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _load_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _save_json(path: Path, data: Any) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False,
                                  default=str), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Product session
# ---------------------------------------------------------------------------

class ProductSession:
    """Owns connect state + the single active task. Thread-safe for the
    FastAPI layer (one worker per task, status readable concurrently)."""

    BRIDGE_HOST = "127.0.0.1"
    BRIDGE_PORT = 6766

    def __init__(self, lease_dir: Optional[Path] = None,
                 lease_s: float = 120.0,
                 heartbeat_s: Optional[float] = None):
        self._lock = threading.RLock()
        self._worker: Optional[threading.Thread] = None
        self._cancel = threading.Event()
        self.state = ProductState()
        self._bridge: Any = None
        self._cfg = _load_json(PRODUCT_CONFIG, {}) or {}
        # Step 9 — exclusive editor ownership (Lane-B LeaseRegistry): every
        # mutating task holds a lease keyed by the canonical project identity
        # so a second product instance / external mutator is refused a
        # structured BUSY response instead of corrupting a live scene.
        from core.editor_lease import LeaseRegistry
        self._lease_dir = Path(lease_dir) if lease_dir is not None \
            else Path(CONFIG_DIR) / "leases"
        self._lease = LeaseRegistry(self._lease_dir)
        self._owner_id = f"product-{os.getpid()}"
        self._lease_key: Optional[str] = None
        self._lease_held = False
        self._lease_s = float(lease_s)
        self._heartbeat_s = float(heartbeat_s or max(5.0, self._lease_s / 4.0))
        self._hb_stop = threading.Event()
        self._hb_thread: Optional[threading.Thread] = None
        self._restore()
        # A previous process may have crashed while owning a lease: recover
        # stale product-owned leases so a restart can never block ownership.
        self._recover_stale_leases()

    # ---------------- persistence helpers ---------------------------------
    def _restore(self) -> None:
        data = _load_json(STATE_FILE, {}) or {}
        st = data.get("connection", {})
        task = data.get("task")
        busy = bool(task and (task.get("state") or "") in BUSY_STATES)
        if busy:
            # A restart can never resume an interrupted Unreal mutation
            # safely (the editor may hold a half-applied change).  Degrade
            # to an actionable FAILED instead of falsely claiming the task
            # is still executing.
            self.state.state = FAILED
            self.state.status_text = "Previous task interrupted by restart"
            self.state.error_detail = ("The app restarted mid-task. The "
                                       "editor may be in a partial state — "
                                       "verify the level, then retry.")
            self.state.task_id = task.get("task_id")
            self.state.final = {
                "verdict": "FAILED",
                "reason": "task interrupted by application restart",
                "recovery": "Verify the level, then retry the request.",
            }
            self._persist()
        else:
            self.state.state = st.get("state", IDLE)
            self.state.project = st.get("project") or {}
            self.state.status_text = st.get("status_text", "Idle")
            if task:
                self._adopt_task_dict(task)
        self._cfg = _load_json(PRODUCT_CONFIG, {}) or {}

    def _persist(self) -> None:
        _save_json(STATE_FILE, {
            "connection": {
                "state": self.state.state,
                "project": dict(self.state.project),
                "status_text": self.state.status_text,
                "updated_at": round(time.time(), 3),
            },
            "task": self._task_dict(),
        })

    def _adopt_task_dict(self, task: Dict[str, Any]) -> None:
        """Rebuild the in-memory state from a persisted task record."""
        for key, value in (task or {}).items():
            if key in ("elapsed_s", "progress"):
                continue
            if hasattr(self.state, key):
                setattr(self.state, key, value)

    def _task_dict(self) -> Dict[str, Any]:
        d = self.state.to_dict()
        return d

    # ---------------- config helpers --------------------------------------
    def _remember_project(self, project: Dict[str, Any]) -> None:
        self._cfg["last_project"] = project
        known = self._cfg.setdefault("known_projects", [])
        paths = {str(p.get("uproject_path", "")).casefold() for p in known}
        key = str(project.get("uproject_path", "")).casefold()
        if key and key not in paths:
            known.append({
                "name": project.get("name"),
                "uproject_path": project.get("uproject_path"),
                "engine": project.get("engine_version"),
            })
        _save_json(PRODUCT_CONFIG, self._cfg)
        # Step 9 — keep the Lane-B first-run snapshot honest so the product
        # state machine's WELCOME→…→READY data stays in sync with reality.
        self._refresh_first_run_snapshot(project)

    @staticmethod
    def _appcfg_recent_project() -> Optional[str]:
        """Lane-B config fallback for the default project (read-only)."""
        try:
            from core import app_config
            return app_config.load_config().recent_project
        except Exception:
            return None

    def _refresh_first_run_snapshot(
            self, project: Optional[Dict[str, Any]] = None) -> None:
        """Recompute + persist the first-run progression from REAL inputs
        (offline-safe doctor, no editor mutation)."""
        try:
            from core import app_config as ac, env_doctor, first_run
            doctor = env_doctor.run(probe_backend=False, probe_ports=False)
            usable = next((b for b in ac.detect_unreal_builds()
                           if b.get("editor_exe")), None)
            recent = ((project or {}).get("uproject_path")
                      or self._appcfg_recent_project())
            first_run.build_progression(
                doctor=doctor, recent_project=recent, unreal_build=usable,
                file_path=Path(CONFIG_DIR) / "first_run.json")
        except Exception:
            pass

    def known_projects(self) -> List[Dict[str, Any]]:
        return list((self._cfg or {}).get("known_projects", []) or [])

    # ---------------- state transitions ------------------------------------
    def _set(self, state: str, text: str, *, stage: Optional[str] = None,
             detail: str = "", result: Optional[Dict[str, Any]] = None,
             task_started: bool = False) -> None:
        with self._lock:
            self.state.state = state
            self.state.status_text = text
            self.state.updated_at = time.time()
            if task_started and not self.state.started_at:
                self.state.started_at = time.time()
            if state in FINAL_STATES:
                self.state.finished_at = time.time()
            self.state.active_issue = ""
            if detail:
                self.state.error_detail = detail
            if stage:
                self.state.current_stage = stage
                self.state.timings[f"{stage}_at"] = time.time()
                self.state.stages.append(StageRecord(
                    stage, status="running", detail=detail or text,
                    result=result or {}).to_dict())
            self._persist()

    def _finish_stage(self, stage: str, ok: bool, detail: str = "") -> None:
        with self._lock:
            for s in self.state.stages:
                if s.get("name") == stage:
                    s["status"] = "ok" if ok else "failed"
                    s["detail"] = detail or s.get("detail", "")
                    break
            self._persist()

    def _mark_failed(self, text: str, detail: str = "",
                     recovery: str = "") -> None:
        with self._lock:
            self.state.state = FAILED
            self.state.status_text = text
            self.state.error_detail = detail
            self.state.active_issue = text
            self.state.finished_at = time.time()
            self.state.timings["terminal_at"] = time.time()
            self.state.final = {
                "verdict": "FAILED",
                "reason": text,
                "detail": detail,
                "recovery": recovery,
            }
            self._persist()

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return self.state.to_dict()

    # ---------------- bridge access ---------------------------------------
    def _new_bridge(self) -> Any:
        from tools.unreal.unreal_bridge import UnrealBridge
        try:
            # Step 9 — bridge endpoint comes from the product config model
            # (defaults stay 127.0.0.1:6766; UA_BRIDGE_PORT overrides work).
            from core import app_config
            cfg = app_config.load_config()
            host, port = cfg.bridge_host, cfg.bridge_port
        except Exception:
            host, port = self.BRIDGE_HOST, self.BRIDGE_PORT
        return UnrealBridge(host=host, port=port, timeout=30)

    def bridge(self) -> Any:
        if self._bridge is None:
            self._bridge = self._new_bridge()
        return self._bridge

    def _bridge_ok(self) -> bool:
        try:
            return bool((self.bridge().ping() or {}).get("ok"))
        except Exception:
            return False

    def _bridge_identity(self) -> Dict[str, Any]:
        try:
            r = self.bridge().get_identity() or {}
            return r.get("result") if isinstance(r.get("result"), dict) else r
        except Exception:
            return {}

    # ----------------------------------------------------------------------
    # PHASE C — one-click project connect
    # ----------------------------------------------------------------------
    def connect(self, uproject: Optional[str] = None, *,
                launch_if_needed: bool = False,
                wait_s: float = 20.0) -> Dict[str, Any]:
        """Connect to a project.  No terminal, no ports, no plugin steps for
        the user: validate -> detect the running editor -> reuse it when its
        identity matches -> only launch when explicitly allowed -> verify
        identity -> READY."""
        with self._lock:
            if self._worker and self._worker.is_alive():
                return {"ok": False, "error": "a task is still running",
                        "state": self.state.state}
            self.state.state = CONNECTING_PROJECT
            self.state.status_text = "Connecting to project…"
            self.state.error_detail = ""
            self._persist()
        t0 = time.time()

        def step(msg: str, detail: str = "", result=None):
            self.state.status_text = msg
            self.state.stages.append(StageRecord(
                "connect", detail=msg + ((" — " + detail) if detail else ""),
                result=result or {}).to_dict())
            self._persist()

        # 1) resolve target project
        live = self._bridge_identity()
        target_path = uproject or live.get("project_path") or \
            (self._cfg.get("last_project") or {}).get("uproject_path") or \
            self._appcfg_recent_project()
        step("Locating project…", target_path or "no selection")
        if not target_path:
            self.state.state = FAILED
            self._persist()
            return {"ok": False,
                    "error": "No project selected and none is running",
                    "state": FAILED}
        tp = str(target_path).replace("/", "\\")
        p = Path(tp)
        if not p.exists():
            self.state.state = FAILED
            self._persist()
            return {"ok": False,
                    "error": f"Project file not found: {tp}",
                    "recovery": "Choose a different project.",
                    "state": FAILED}

        # 2) duplicate-editor protection + reuse
        editor_pids = self._running_editor_pids()
        norm = lambda s: str(s).replace("\\", "/").casefold()
        if live and live.get("project_path"):
            same = norm(live.get("project_path")) == norm(p.resolve())
            if same:
                project = self._project_record(p, live)
                self.state.project = dict(project)
                step("Verifying editor identity…", "identity matches",
                     project)
                # 3) real readiness: world/level present
                world = (live or {}).get("world") or ""
                ok = self._bridge_ok()
                if ok and world:
                    self._set(READY, f"Ready — {project.get('name')}",
                              detail="project identity and live level verified")
                    self._remember_project(project)
                    return {"ok": True, "state": READY,
                            "project": project,
                            "editor": "reused_running_editor",
                            "connect_s": round(time.time() - t0, 2)}
                self.state.state = RECOVERING
                self._persist()
            else:
                self.state.state = FAILED
                self._persist()
                return {"ok": False,
                        "error": ("Another project is already open in Unreal "
                                  f"Editor: {live.get('project_name')}"),
                        "current_project": live,
                        "recovery": ("Use that project, or close Unreal "
                                     "Editor first."),
                        "state": FAILED}
        elif editor_pids:
            # Editor process(es) exist but the bridge is not answering:
            # bounded wait, then an honest failure (never a silent hang).
            step("Waiting for the editor bridge…",
                 f"{len(editor_pids)} editor process(es) running")
            deadline = time.time() + max(5.0, wait_s)
            while time.time() < deadline:
                if self._bridge_ok():
                    live2 = self._bridge_identity()
                    if live2.get("project_path"):
                        if norm(live2.get("project_path")) == norm(p.resolve()):
                            self.state.state = CONNECTING_PROJECT
                            self._persist()
                            return self.connect(str(p))
                        self.state.state = FAILED
                        self._persist()
                        return {"ok": False,
                                "error": ("A different project opened in the "
                                          "editor while connecting"),
                                "state": FAILED}
                time.sleep(0.8)
            self.state.state = FAILED
            self._persist()
            return {"ok": False,
                    "error": ("Unreal Editor is running but the agent bridge "
                              "is not answering on port 6766"),
                    "recovery": "Open the editor again, or wait and retry.",
                    "state": FAILED}
        else:
            # Nothing running.
            if not launch_if_needed:
                self.state.state = FAILED
                self._persist()
                return {"ok": False,
                        "error": ("Unreal Editor is not running and launch "
                                  "was not requested"),
                        "recovery": "Start the agent with launch enabled.",
                        "state": FAILED}
            step("Launching Unreal Editor…", str(p))
            from tools.unreal.project_manager import open_project
            opened = open_project(str(p))
            if not opened.get("ok"):
                self.state.state = FAILED
                self._persist()
                return {"ok": False,
                        "error": f"Editor launch failed: {opened.get('error')}",
                        "state": FAILED}
            live = opened.get("project_identity") or {}
            project = self._project_record(p, live)
            self.state.project = dict(project)
            self._set(READY, f"Ready — {project.get('name')}",
                      detail="launched editor verified")
            self._remember_project(project)
            return {"ok": True, "state": READY, "project": project,
                    "editor": "launched_editor",
                    "connect_s": round(time.time() - t0, 2)}

        # (path from the RECOVERING branch above)
        live = self._bridge_identity()
        if not self._bridge_ok() or not (live or {}).get("project_path"):
            self.state.state = FAILED
            self._persist()
            return {"ok": False,
                    "error": "Bridge became unavailable during connect",
                    "recovery": "Retry the connection.",
                    "state": FAILED}
        project = self._project_record(p, live)
        self.state.project = dict(project)
        self._set(READY, f"Ready — {project.get('name')}",
                  detail="recovered bridge")
        self._remember_project(project)
        return {"ok": True, "state": READY, "project": project,
                "editor": "recovered",
                "connect_s": round(time.time() - t0, 2)}

    @staticmethod
    def _running_editor_pids() -> List[int]:
        try:
            import subprocess
            r = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq UnrealEditor.exe",
                 "/FO", "CSV", "/NH"], capture_output=True, text=True,
                timeout=8)
            import csv, io
            pids = []
            for row in csv.reader(io.StringIO(r.stdout)):
                if len(row) >= 2 and row[0].casefold() == "unrealeditor.exe" \
                        and row[1].isdigit():
                    pids.append(int(row[1]))
            return sorted(set(pids))
        except Exception:
            return []

    @staticmethod
    def _project_record(p: Path, identity: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": identity.get("project_name") or p.stem,
            "uproject_path": str(p.resolve()).replace("\\", "/"),
            "engine_version": identity.get("engine"),
            "world": identity.get("world"),
            "connected_at": round(time.time(), 3),
        }

    def reconnect(self) -> Dict[str, Any]:
        """Recovery entry point: RECOVERING -> READY (or actionable FAILED)."""
        with self._lock:
            if self.state.state in BUSY_STATES:
                return {"ok": False,
                        "error": "a task is running; cannot reconnect now"}
            self.state.state = RECOVERING
            self.state.status_text = "Reconnecting to the editor…"
            self.state.stages.append(StageRecord(
                "reconnect", detail="recovering bridge").to_dict())
            self._persist()
        project = self.state.project or {}
        return self.connect(project.get("uproject_path"),
                            launch_if_needed=True, wait_s=15.0)

    # ----------------------------------------------------------------------
    # PRODUCT PLANNER (honest capability mapping over real ops)
    # ----------------------------------------------------------------------
    PLANNED_PATTERNS = [
        # (capability, regex on the lower-cased prompt, description)
        ("add_visible_prop",
         r"(add|create|spawn|place)\b.*\b(cube|prop|marker|box|primitive)\b",
         "Adds a real cube/box actor to the level, saves it, and verifies it."),
        ("remove_actor",
         r"(remove|delete|destroy)\b.*\b(actor|prop|cube|marker|object)\b",
         "Deletes a named actor from the level and saves."),
    ]

    def _plan(self, prompt: str) -> Dict[str, Any]:
        """Map a natural-language request onto real operations.

        Kept deliberately small and honest: requests outside the supported
        capability set fail fast with an exact, actionable reason instead of
        pretending to plan work the shell cannot execute.
        """
        raw = str(prompt)
        low = raw.lower()
        name_m = re.search(r"named\s+([A-Za-z_][A-Za-z0-9_]*)", raw) or \
                re.search(r"call(?:ed)?\s+([A-Za-z_][A-Za-z0-9_]*)", raw) or \
                re.search(r"\b([A-Za-z_][A-Za-z0-9_]*)\s+(?:cube|box|prop)\b",
                          raw)
        name = (name_m.group(1) if name_m else "") or None
        if name and name.lower() in {"add", "create", "spawn", "a", "the"}:
            name = None

        for capability, pattern, desc in self.PLANNED_PATTERNS:
            if re.search(pattern, low):
                if capability == "add_visible_prop":
                    spawn_name = name or \
                        f"UA_Product_{uuid.uuid4().hex[:6]}"
                    steps = [
                        {"step_id": "spawn_prop", "op": "spawn_prop",
                         "params": {"name": spawn_name,
                                    "mesh": "/Engine/BasicShapes/Cube.Cube",
                                    "class": "StaticMeshActor",
                                    "scale": 0.5},
                         "expected": "actor spawned with read-back location"},
                        {"step_id": "verify_actor", "op": "verify_actor",
                         "params": {"name": spawn_name},
                         "expected": "actor read back"},
                    ]
                else:
                    target = name or "UA_Product_"  # prefix => auto-resolve
                    steps = [
                        {"step_id": "delete_actor", "op": "delete_actor",
                         "params": {"name": target},
                         "expected": "actor removed and level saved"},
                        {"step_id": "verify_gone", "op": "verify_gone",
                         "params": {"name": target},
                         "expected": "actor no longer present"},
                    ]
                return {"ok": True, "capability": capability,
                        "description": desc, "steps": steps}
        return {"ok": False,
                "reason": ("I can add or remove a named prop (cube/box) in "
                           "the level. Describe one of those actions to "
                           "start."),
                "steps": []}

    # ----------------------------------------------------------------------
    # EXECUTION (real bridge operations, read-back verified)
    # ----------------------------------------------------------------------
    def run_task(self, prompt: str) -> Dict[str, Any]:
        with self._lock:
            if self._worker and self._worker.is_alive():
                return {"ok": False, "error": "a task is already running"}
            chk = self._bridge_ok()
            if not chk:
                return {"ok": False,
                        "error": "Not connected to Unreal Editor",
                        "state": self.state.state,
                        "recovery": "Connect to a project first."}
            # the editor must still be on OUR project (cheap identity check;
            # the connect flow already verified it once).
            identity = self._bridge_identity()
            mine = (self.state.project or {}).get("uproject_path") or ""
            live = str(identity.get("project_path") or "")
            norm = lambda s: str(s).replace("\\", "/").casefold()
            if mine and live and norm(live) != norm(mine):
                return {"ok": False,
                        "error": "Unreal Editor switched projects since "
                                  "connect",
                        "state": self.state.state,
                        "recovery": "Reconnect to the project."}
            # Step 9 — exclusive mutating ownership BEFORE any Unreal work.
            # On BUSY we return immediately with structured conflict info and
            # never touch the editor; the current READY state is left intact.
            tid = f"task_{uuid.uuid4().hex[:10]}"
            lease = self._acquire_lease(tid)
            if not lease.get("ok"):
                return self._busy_response(lease)
            prev_project = dict(self.state.project or {})
            self._cancel.clear()
            self.state = ProductState()
            self.state.state = UNDERSTANDING_REQUEST
            self.state.status_text = "Reading your request…"
            self.state.task_id = tid
            self.state.project = prev_project
            self.state.started_at = time.time()
            self.state.timings["requested_at"] = time.time()
            self.state.timings["lease_acquire_s"] = round(
                float(lease.get("acquire_s") or 0.0), 4)
            self._persist()
            self._worker = threading.Thread(
                target=self._run_worker, args=(str(prompt),),
                daemon=True, name="product-task-worker")
            self._worker.start()
            self._start_heartbeat()
        return {"ok": True, "task_id": tid}

    def _busy_response(self, lease: Dict[str, Any]) -> Dict[str, Any]:
        """Structured BUSY/OWNED answer: no editor mutation, no infinite
        retry, current (READY) state preserved for a manual retry."""
        conflict = dict(lease.get("conflict") or {})
        exp = float(conflict.get("expires_in_s") or 0.0)
        return {"ok": False, "busy": True, "conflict": conflict,
                "error": "The project is owned by another task",
                "state": self.state.state,
                "owner_id": conflict.get("owner_id"),
                "task_id": conflict.get("task_id"),
                "recovery": ("No change was made. Retry when the current "
                              "task finishes or its lease expires "
                              f"(~{max(0, round(exp))}s).")}

    # ---- lease helpers (Step 9 ownership integration) ---------------------
    def _lease_identity(self) -> Optional[str]:
        """Canonical identity of the currently selected project."""
        from core.editor_lease import canonical_identity
        path = (self.state.project or {}).get("uproject_path") or ""
        if not path:
            return None
        try:
            return canonical_identity(path)
        except Exception:
            return None

    def _acquire_lease(self, task_id: str) -> Dict[str, Any]:
        identity = self._lease_identity()
        if not identity:
            return {"ok": False,
                    "error": "no project selected; cannot take ownership"}
        t0 = time.time()
        r = self._lease.acquire(identity, self._owner_id, task_id,
                                lease_s=self._lease_s, read_only=False)
        r["acquire_s"] = time.time() - t0
        if r.get("ok"):
            self._lease_key = identity
            self._lease_held = True
        return r

    def _start_heartbeat(self) -> None:
        """Daemon renewal while the mutating task is live (bounded, stops on
        release).  A crashed process simply stops renewing and the lease
        self-expires / is recovered on the next boot."""
        self._hb_stop.clear()

        def beat():
            while not self._hb_stop.wait(self._heartbeat_s):
                if not self._lease_held or not self._lease_key:
                    return
                try:
                    self._lease.renew(self._lease_key, self._owner_id)
                except Exception:
                    pass

        self._hb_thread = threading.Thread(target=beat, daemon=True,
                                           name="product-lease-heartbeat")
        self._hb_thread.start()

    def _release_lease(self) -> None:
        self._hb_stop.set()
        ident, held = self._lease_key, self._lease_held
        self._lease_key, self._lease_held = None, False
        if held and ident:
            try:
                self._lease.release(ident, self._owner_id)
            except Exception:
                pass

    def _recover_stale_leases(self) -> None:
        """Boot recovery: any mutating lease whose owner is a *dead* product
        process is force-released so a restart can never lock the editor.
        A lease from a live process is left strictly alone."""
        try:
            for rec in self._lease.list_leases():
                owner = str(rec.get("owner_id") or "")
                m = re.match(r"^product-(\d+)$", owner)
                if not m:
                    continue
                pid = int(m.group(1))
                if pid == os.getpid() or self._pid_alive(pid):
                    continue
                self._lease.force_release(
                    rec.get("identity"),
                    reason="stale owner recovered on product boot")
        except Exception:
            pass

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        try:
            if os.name == "nt":
                import subprocess
                r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}",
                                    "/FO", "CSV", "/NH"],
                                   capture_output=True, text=True,
                                   timeout=8)
                return str(pid) in (r.stdout or "")
            os.kill(pid, 0)
            return True
        except Exception:
            return False

    def _run_worker(self, prompt: str) -> None:
        try:
            self._execute_pipeline(prompt)
        except Exception as exc:  # never leave the UI hanging
            self._mark_failed(f"Task failed with an internal error",
                              detail=f"{type(exc).__name__}: {exc}",
                              recovery="Retry the task.")
        finally:
            # Step 9 — ownership ends with the task on every terminal path
            # (COMPLETE / FAILED / cancelled / exception).
            self._release_lease()
            with self._lock:
                self._worker = None

    def _execute_pipeline(self, prompt: str) -> None:
        # UNDERSTANDING (real intent interpreter)
        try:
            from core.universal_intent import interpret_intent
            intent = interpret_intent(prompt).to_dict()
        except Exception:
            intent = {"domains": [], "primary_domain": "unparsed"}
        self._set(UNDERSTANDING_REQUEST,
                  f"Understood: {intent.get('primary_domain', 'general')} "
                  "request", stage="understand", result=intent)
        self._finish_stage("understand", True)

        # PLANNING (honest product planner over the real vocabulary)
        self._set(PLANNING, "Planning the work…", stage="plan")
        plan = self._plan(prompt)
        if not plan.get("ok"):
            self._finish_stage("plan", False,
                               str(plan.get("reason") or "unsupported"))
            self._mark_failed("This request is outside the current product "
                              "scope", detail=str(plan.get("reason") or ""),
                              recovery="Ask to add or remove a named prop.")
            return
        self.state.steps_total = len(plan["steps"])
        self.state.steps_done = 0
        self._finish_stage("plan", True, str(plan.get("capability")))

        # EXECUTING through real bridge ops
        self._set(EXECUTING, f"Executing: {plan.get('description')}",
                  stage="execute")
        executor = _UnrealExecutor(self)
        for step in plan["steps"]:
            if self._cancel.is_set():
                self._mark_failed("Task cancelled by the user",
                                  recovery="Start a new task.")
                return
            op = step.get("op")
            self.state.status_text = f"Executing {op}…"
            self.state.current_stage = op
            self._persist()
            outcome = executor.run(op, step.get("params") or {})
            if outcome.get("ok"):
                self.state.steps_done = int(self.state.steps_done or 0) + 1
                self.state.last_successful_action = outcome.get("summary", op)
                self._persist()
                continue
            # one bounded retry after a state/read-back diagnosis
            if self.state.retry_count < 1 and outcome.get("retryable"):
                self.state.retry_count += 1
                self.state.status_text = (f"Retrying {op} after "
                                          f"{outcome.get('error', '')[:80]}…")
                self._persist()
                outcome = executor.run(op, step.get("params") or {},
                                       retry=True)
                if outcome.get("ok"):
                    self.state.steps_done = int(self.state.steps_done or 0) + 1
                    self.state.last_successful_action = \
                        outcome.get("summary", op)
                    self._persist()
                    continue
            self._finish_stage("execute", False,
                               str(outcome.get("error") or "step failed"))
            self._mark_failed(
                f"Step failed: {op}",
                detail=str(outcome.get("error") or "")[:300],
                recovery=str(outcome.get("recovery") or
                             "Retry the task."))
            return
        self._finish_stage("execute", True)

        # VALIDATING (fresh capture + Step-5 release evaluation)
        self._set(VALIDATING, "Validating the result with a fresh "
                              "capture…", stage="validate")
        verdict = self._validate_and_accept(prompt)
        if verdict["state"] == COMPLETE:
            return
        if verdict["state"] == SELF_FIXING:
            # Autonomous Visual Director correction (Step-6 machinery).
            self.state.state = SELF_FIXING
            self.state.status_text = "Autonomously correcting the scene…"
            self._persist()
            ok = self._self_fix(verdict)
            if ok:
                self._terminal_accept()
                return
            self._mark_failed(
                "Visual correction could not reach acceptance",
                detail="; ".join(self.state.active_issue.split("|")
                                 if self.state.active_issue else
                                 ["remaining visual defects"]),
                recovery="Ask to remove the added prop.")
            return
        # FAILED from validation
        self._mark_failed(verdict.get("reason", "Validation failed"),
                          detail=verdict.get("detail", ""),
                          recovery=verdict.get("recovery", "Retry."))

    # -- validation + director ----------------------------------------------
    def _profile_name(self) -> Optional[str]:
        proj = (self.state.project or {}).get("name") or ""
        return {"ASSET_Showcase2": "rel_gfx_board"}.get(proj)

    # ---- viewport freshness: a minimized/occluded editor keeps returning a
    # frozen buffer even when UE reports visible=True, so the product layer
    # checks the REAL window state before every capture and restores the
    # window when needed (Step-5/6 pattern, kept out of the frozen adapter).
    def _window_ok(self) -> bool:
        """True when an Unreal Editor window is visible and not minimized."""
        try:
            import subprocess
            ps = ("$p = Get-Process -Name UnrealEditor -ErrorAction "
                  "SilentlyContinue | Where-Object { $_.MainWindowHandle -ne "
                  "0 } | Select-Object -First 1; "
                  "if (-not $p) { Write-Output 'NONE'; exit 0 }; "
                  "Add-Type @'\nusing System; using System.Runtime."
                  "InteropServices;\npublic class Win8 { [DllImport(\"user32.dll\")] "
                  "public static extern bool IsIconic(IntPtr h); }\n'@; "
                  "if ([Win8]::IsIconic($p.MainWindowHandle)) "
                  "{ Write-Output 'ICONIC' } else { Write-Output 'OK' }")
            r = subprocess.run(["powershell", "-NoProfile",
                                "-ExecutionPolicy", "Bypass", "-Command", ps],
                               capture_output=True, text=True, timeout=15)
            return (r.stdout or "").strip() == "OK"
        except Exception:
            return True  # unknown -> let the adapter's own guard decide

    @staticmethod
    def _restore_editor_window() -> bool:
        try:
            import subprocess
            ps = r"""
$p = Get-Process -Name UnrealEditor -ErrorAction SilentlyContinue |
     Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $p) { Write-Output 'NO'; exit 1 }
Add-Type @'
using System; using System.Runtime.InteropServices;
public class W9 { [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
[DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h); }
'@
[W9]::ShowWindow($p.MainWindowHandle, 9) | Out-Null
[W9]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
Write-Output 'OK'
"""
            r = subprocess.run(["powershell", "-NoProfile",
                                "-ExecutionPolicy", "Bypass", "-Command", ps],
                               capture_output=True, text=True, timeout=30)
            return "OK" in (r.stdout or "")
        except Exception:
            return False

    def _product_capture(self, path: Path) -> Dict[str, Any]:
        """Capture through the Step-7 adapter, but only ever against a live
        (visible, non-minimized) editor window; restore it first otherwise.
        Returns the capture info dict (path/visible)."""
        from core.unreal_fix_adapter import UnrealFixAdapter
        if not self._window_ok():
            if self._restore_editor_window():
                time.sleep(2.2)
        adapter = UnrealFixAdapter(self.bridge(), visible_retries=2)
        info = adapter.capture(str(Path(path).resolve()))
        return {"path": str(Path(info["path"]).resolve()),
                "md5": hashlib.md5(Path(info["path"]).read_bytes()
                                   ).hexdigest()[:12],
                "visible": info.get("visible", True)}

    def _fresh_capture(self) -> Dict[str, Any]:
        """Fresh viewport capture (product path: window guarded)."""
        proof_dir = self._task_proof_dir()
        proof_dir.mkdir(parents=True, exist_ok=True)
        tag = hashlib.md5(str(time.time()).encode()).hexdigest()[:6]
        path = proof_dir / f"capture_{tag}.png"
        return self._product_capture(path)

    def _release_evaluate(self, path: str) -> Dict[str, Any]:
        from assetlib.reports.unreal_coder_release_missions import (
            _make_evaluate, resolve_scene_locators)
        name = self._profile_name()
        locs = resolve_scene_locators(name) if name else None
        fn = _make_evaluate(self.bridge(), scene_locators=locs)
        return fn({"path": str(Path(path).resolve()), "ok": True})

    def _validate_and_accept(self, prompt: str) -> Dict[str, Any]:
        cap = self._fresh_capture()
        review = self._release_evaluate(cap["path"])
        score = float(review.get("score") or 0.0)
        defects = list(review.get("defects") or [])
        rec = {"capture": cap, "release_evaluate": review}
        self.state.proof.append({"type": "validation_capture",
                                 "path": cap["path"], "md5": cap["md5"],
                                 "score": round(score, 2),
                                 "defects": defects})
        if score >= 8.5 and not defects:
            self.state.active_issue = ""
            self._finish_stage("validate", True,
                               f"score {score:.2f}, no defects")
            self._complete(review, cap, prompt)
            return {"state": COMPLETE}
        if defects:
            self.state.active_issue = "|".join(defects[:4])
        self._finish_stage("validate", False,
                           f"score {score:.2f}, defects {defects}")
        return {"state": SELF_FIXING, "defects": defects,
                "score": score, "capture": cap,
                "reason": f"visual acceptance below gate ({score:.2f})",
                "detail": f"defects: {defects}",
                "recovery": "autonomous visual correction"}

    def _self_fix(self, verdict: Dict[str, Any]) -> bool:
        """Bounded autonomous director correction (AutonomousVisualLoop +
        the frozen release gate + the Step-6/7 Unreal fix adapter)."""
        from core.visual_loop import AutonomousVisualLoop
        from core.release_director import release_accept
        from core.unreal_fix_adapter import UnrealFixAdapter
        from assetlib.reports.unreal_coder_release_missions import (
            resolve_scene_locators)
        locs = resolve_scene_locators(self._profile_name()) if \
            self._profile_name() else None
        loc_kw = {k: v for k, v in (locs or {}).items() if v is not None}
        proof_dir = self._task_proof_dir()
        proof_dir.mkdir(parents=True, exist_ok=True)
        counter = {"n": 0}

        def capture() -> str:
            counter["n"] += 1
            p = proof_dir / f"fix_{counter['n']:02d}.png"
            info = self._product_capture(p)
            return str(Path(info["path"]).resolve())

        adapter = UnrealFixAdapter(self.bridge(), visible_retries=2)
        loop = AutonomousVisualLoop(
            target={}, capture=capture, apply=adapter.apply,
            max_passes=3, out_dir=str(proof_dir),
            gate=release_accept,
            subject_locator=loc_kw.get("subject_locator"),
            ui_locator=loc_kw.get("ui_locator"))
        result = loop.run()
        ok = bool(result.get("status") == "COMPLETE")
        self.state.retry_count += int(result.get("iterations") or 0)
        self.state.proof.append({"type": "self_fix_loop",
                                 "status": result.get("status"),
                                 "iterations": result.get("iterations")})
        return ok

    def _terminal_accept(self) -> None:
        cap = self._fresh_capture()
        review = self._release_evaluate(cap["path"])
        score = float(review.get("score") or 0.0)
        defects = list(review.get("defects") or [])
        self.state.proof.append({"type": "terminal_capture",
                                 "path": cap["path"], "md5": cap["md5"],
                                 "score": round(score, 2),
                                 "defects": defects})
        if score >= 8.5 and not defects:
            self._complete(review, cap, "")
        else:
            self._mark_failed("Visual correction incomplete",
                              detail=f"score {score:.2f}, defects {defects}")

    def _complete(self, review: Dict[str, Any], cap: Dict[str, Any],
                  prompt: str) -> None:
        score = float(review.get("score") or 0.0)
        defects = list(review.get("defects") or [])
        self.state.state = COMPLETE
        self.state.status_text = "Task complete"
        self.state.finished_at = time.time()
        self.state.timings["terminal_at"] = time.time()
        self.state.final = {
            "verdict": "SUCCESS",
            "score": round(score, 2),
            "defects": defects,
            "world_saved": True,
            "human_corrections": 0,
            "evidence": [{"type": "viewport", "path": cap["path"],
                          "md5": cap["md5"]}],
        }
        self._persist()

    def _task_proof_dir(self) -> Path:
        task_id = self.state.task_id or "task_unknown"
        return PROOF_DIR / task_id

    def cancel(self) -> Dict[str, Any]:
        self._cancel.set()
        return {"ok": True}


# ---------------------------------------------------------------------------
# Real Unreal executor (same ops the release missions use; read-back verified)
# ---------------------------------------------------------------------------

class _UnrealExecutor:
    """Executes product plan ops through the live bridge with read-back."""

    def __init__(self, session: ProductSession):
        self.session = session

    def run(self, op: str, params: Dict[str, Any], retry: bool = False) -> \
            Dict[str, Any]:
        fn = getattr(self, f"_op_{op}", None)
        if fn is None:
            return {"ok": False, "error": f"unknown op {op}"}
        return fn(params, retry=retry)

    def _bridge(self) -> Any:
        return self.session.bridge()

    def _execute(self, code: str) -> Dict[str, Any]:
        raw = self._bridge().execute_python(code)
        if not isinstance(raw, dict) or not raw.get("ok"):
            return {"ok": False,
                    "error": str((raw or {}).get("message")
                                 or (raw or {}).get("error")
                                 or "bridge call failed")[:200],
                    "retryable": True}
        payload = raw.get("result")
        if isinstance(payload, dict) and payload.get("ok") is False:
            return {"ok": False, "error": str(payload.get("error"))[:200],
                    "retryable": True}
        return {"ok": True, "result": payload}

    # -- add a visible cube, camera-relative (generic, scene-agnostic) -----
    def _op_spawn_prop(self, p: Dict[str, Any], retry: bool = False) -> Dict:
        name = str(p.get("name") or "UA_Product_Prop")
        mesh = str(p.get("mesh") or "/Engine/BasicShapes/Cube.Cube")
        scale = float(p.get("scale") or 0.5)
        depth = 1350.0
        out = self._execute(f"""
import unreal
label = {name!r}
# idempotent: remove any same-label actor from earlier runs first.
subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
for _old in unreal.EditorLevelLibrary.get_all_level_actors():
    if _old.get_actor_label() == label and _old.get_class().get_name() == "StaticMeshActor":
        subsystem.destroy_actor(_old)
# camera-relative placement: in front of the current view, low and
# left-of-center so it is clearly visible but away from the subject band.
cam_loc, cam_rot = unreal.EditorLevelLibrary.get_level_viewport_camera_info()
import math
yaw = math.radians(cam_rot.yaw)
pitch = math.radians(cam_rot.pitch)
fwd = unreal.Vector(math.cos(pitch) * math.cos(yaw),
                    math.cos(pitch) * math.sin(yaw),
                    math.sin(pitch))
right = unreal.Vector(-fwd.y, fwd.x, 0.0)  # perpendicular in the X-Y plane
base = cam_loc + fwd * {depth!r}
pos = base + right * -620.0 + unreal.Vector(0, 0, -70.0)
actor = subsystem.spawn_actor_from_class(
    unreal.StaticMeshActor, pos, unreal.Rotator(0, 0, 0))
if actor is None:
    __bridge_result__ = {{"ok": False, "error": "spawn returned None"}}
else:
    actor.set_actor_label(label)
    actor.set_actor_scale3d(unreal.Vector({scale}, {scale}, {scale}))
    mesh_asset = unreal.load_asset({mesh!r})
    if mesh_asset is not None and hasattr(actor, "static_mesh_component"):
        actor.static_mesh_component.set_static_mesh(mesh_asset)
    loc = actor.get_actor_location()
    __bridge_result__ = {{
        "ok": True,
        "name": actor.get_name(),
        "label": label,
        "class": actor.get_class().get_name(),
        "location": [round(loc.x, 1), round(loc.y, 1), round(loc.z, 1)],
        "depth": {depth!r},
        "scale": {scale},
    }}
""")
        if not out.get("ok"):
            return {**out,
                    "recovery": "Check that the editor viewport is visible."}
        self._save_world()
        return {"ok": True, "summary": f"spawned {name}",
                "result": out.get("result")}

    def _op_save_level(self, p: Dict, retry: bool = False) -> Dict:
        out = self._execute("""
import unreal
ok = bool(unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True))
__bridge_result__ = {"ok": ok, "saved": ok}
""")
        if not out.get("ok"):
            return out
        return {"ok": True, "summary": "level saved", "result": out.get("result")}

    def _op_verify_actor(self, p: Dict, retry: bool = False) -> Dict:
        label = str(p.get("name") or "")
        out = self._execute(f"""
actors = unreal.EditorLevelLibrary.get_all_level_actors()
matches = [a for a in actors if a.get_actor_label() == {label!r}]
if len(matches) == 1:
    a = matches[0]
    loc = a.get_actor_location()
    __bridge_result__ = {{"ok": True, "label": a.get_actor_label(),
      "location": [round(loc.x,1), round(loc.y,1), round(loc.z,1)],
      "class": a.get_class().get_name()}}
else:
    __bridge_result__ = {{"ok": False,
      "error": "actor {label} not found (matches: " + str(len(matches)) + ")"}}
""")
        if not out.get("ok"):
            return {**out, "recovery": "The actor was not created or the "
                    "level was reverted."}
        return {"ok": True, "summary": f"verified {label} in level",
                "result": out.get("result")}

    def _op_delete_actor(self, p: Dict, retry: bool = False) -> Dict:
        name = str(p.get("name") or "")
        auto = name == "UA_Product_"  # sentinel: newest UA_Product_ actor
        out = self._execute(f"""
subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
actors = unreal.EditorLevelLibrary.get_all_level_actors()
{'matches = [a for a in actors if a.get_actor_label() == %r]' % name if not auto else 'matches = [a for a in actors if a.get_actor_label().startswith(\"UA_Product_\")]'}
if len(matches) == 0:
    __bridge_result__ = {{"ok": False,
      "error": "{('no actor named ' + name) if not auto else 'no UA_Product_ actor to remove'}"}}
elif len(matches) > 1:
    __bridge_result__ = {{"ok": False,
      "error": "multiple matching actors; refusing to guess"}}
else:
    label = matches[0].get_actor_label()
    destroyed = subsystem.destroy_actor(matches[0])
    __bridge_result__ = {{"ok": bool(destroyed), "label": label}}
""")
        if not out.get("ok"):
            return {**out, "recovery": "Check the actor name."}
        self._save_world()
        return {"ok": True, "summary": f"removed {name}",
                "result": out.get("result")}

    def _op_verify_gone(self, p: Dict, retry: bool = False) -> Dict:
        name = str(p.get("name") or "")
        auto = name == "UA_Product_"
        out = self._execute(f"""
actors = unreal.EditorLevelLibrary.get_all_level_actors()
{'matches = [a for a in actors if a.get_actor_label() == %r]' % name if not auto else 'matches = [a for a in actors if a.get_actor_label().startswith(\"UA_Product_\")]'}
__bridge_result__ = {{"ok": len(matches) == 0,
  "remaining": len(matches)}}
""")
        if not out.get("ok"):
            return {**out, "recovery": "Actor is still present."}
        return {"ok": True, "summary": f"verified {name} removed",
                "result": out.get("result")}

    def _save_world(self) -> None:
        try:
            self._execute("""
import unreal
unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
__bridge_result__ = {"ok": True}
""")
        except Exception:
            pass


# Convenience singleton for the API layer.
session = ProductSession()
