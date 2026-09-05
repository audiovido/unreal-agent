"""code_tasks.py — Aivido Autonomous Supervisor: code-task routing + worker.

Adds the missing automatic REPO/CODE execution path on top of the existing
(unchanged) Unreal mission pipeline. Unreal/editor/content prompts keep going
to the mission pipeline (start_task -> /api/unreal-coder/*); repository/code
tasks are executed here by a deterministic, safety-gated code worker.

Ownership rules (single mutation owner):
  * The code worker NEVER edits the live main checkout. Repository edits
    happen inside an isolated git worktree on its own branch created from
    the repo's committed HEAD; the worktree is removed afterwards and the
    verified commit survives only as an isolated branch ref + patch file.
  * Only NEW files are created (never overwriting anything in the live
    tree), so an isolated task can never clobber other agents' work.
  * One code task runs at a time (single-flight loop).

Task lifecycle (durable, memory/code_tasks/state.json):
  queued -> running -> passed(verdict PASS) | failed | blocked | cancelled
  Auto-advance: after a PASS the runner picks the next eligible task
  (dependencies satisfied + not blocked), ordered by priority then age,
  and keeps going without human confirmation. A watchdog resumes the loop
  whenever eligible work exists and the loop is idle (incl. after restart).

Verdict honesty:
  PASS is only ever recorded after every acceptance check passed AND every
  requested test exited 0 AND the changed-file set is exactly within the
  declared scope AND the verified commit landed on the isolated branch.
  Anything the worker cannot safely auto-implement is BLOCKED with exact
  evidence, never silently skipped.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

try:  # FastAPI present in the backend venv
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel, Field
except Exception:  # pragma: no cover - non-API import (tests import module directly)
    APIRouter = None
    BaseModel = object
    Field = None
    HTTPException = Exception

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STATE_DIR = Path(os.environ.get(
    "AIVIDO_CODE_STATE_DIR", str(ROOT / "memory" / "code_tasks")))
STATE_FILE = STATE_DIR / "state.json"
WORKTREES_DIR = STATE_DIR / "worktrees"
EVIDENCE_DIR = STATE_DIR / "evidence"
BACKEND_URL = os.environ.get("AIVIDO_BACKEND_URL", "http://127.0.0.1:8765")
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

MAX_ATTEMPTS = 3
WATCHDOG_INTERVAL_S = 4.0
STATE_LOCK = threading.RLock()
_RUNNER_THREAD: Optional[threading.Thread] = None
_RUNNING_LOOP = False

# Only these top-level roots may receive NEW files from an autonomous task.
ALLOWED_ROOTS = ("app", "core", "tests", "tools", "scripts", "docs", "supervisor")
# Status vocabulary
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_PASSED = "passed"      # verdict PASS -> reported COMPLETE after queue advance
STATUS_FAILED = "failed"      # attempts exhausted, verdict FAIL
STATUS_BLOCKED = "blocked"    # true blocker, verdict BLOCKED (evidence written)
STATUS_CANCELLED = "cancelled"
TERMINAL = {STATUS_PASSED, STATUS_FAILED, STATUS_BLOCKED, STATUS_CANCELLED}

CODE_WORDS = (
    "repo", "repository", "code", "file", "refactor", "test", "cleanup",
    "clean up", "script", "lint", "bug", "fix", "function", "module",
    "pytest", "import", "class", "api endpoint", "gateway tool", "docs",
    "documentation", "readme", "py",
)
UNREAL_WORDS = (
    "unreal", "editor", "blueprint", "level", "asset", "material", "mesh",
    "sequencer", "render", "niagara", "metahuman", "landscape", "pcg",
    "viewport", "actor", "world", "map ", "engine", "bridge", "pie", "texture",
    "lighting", "camera", "showcase", "mission",
)


# ---------------------------------------------------------------------------
# Durable state helpers
# ---------------------------------------------------------------------------

def _ensure_dirs() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    WORKTREES_DIR.mkdir(parents=True, exist_ok=True)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)


def _default_state() -> Dict[str, Any]:
    return {
        "version": 1,
        "updated_at": time.time(),
        "next_seq": 1,
        "tasks": [],
    }


def _load_state() -> Dict[str, Any]:
    _ensure_dirs()
    if not STATE_FILE.exists():
        return _default_state()
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("tasks"), list):
            return data
    except Exception:
        pass
    return _default_state()


def _save_state(data: Dict[str, Any]) -> None:
    _ensure_dirs()
    data["updated_at"] = time.time()
    tmp = STATE_DIR / f"state.{uuid.uuid4().hex}.tmp"
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def _mutate(mutator) -> Any:
    """Run a read-modify-write against the durable state under the lock."""
    with STATE_LOCK:
        data = _load_state()
        result = mutator(data)
        _save_state(data)
        return result


def _new_task_id(data: Dict[str, Any]) -> str:
    task_id = f"ct{data.get('next_seq', 1):04d}"
    data["next_seq"] = int(data.get("next_seq", 1)) + 1
    return task_id


# ---------------------------------------------------------------------------
# Routing classifier (conservative; explicit routing wins)
# ---------------------------------------------------------------------------

def classify_routing(prompt: str, hint: Optional[str] = None) -> str:
    """Return 'code' | 'unreal' | 'mixed' for a task prompt."""
    if hint in ("code", "unreal", "mixed"):
        return hint
    text = f" {str(prompt or '').lower()} "
    code_hits = sum(1 for w in CODE_WORDS if f" {w} " in text or text.endswith(f" {w} "))
    unreal_hits = sum(1 for w in UNREAL_WORDS if f" {w} " in text or text.endswith(f" {w} "))
    # Repository + editor intent together => mixed (run code stage, then the
    # Unreal stage in dependency order).
    if code_hits >= 2 and unreal_hits >= 1:
        return "mixed"
    if code_hits >= 2 and code_hits >= unreal_hits:
        return "code"
    if unreal_hits > code_hits:
        return "unreal"
    if code_hits >= 2:
        return "code"
    return "unreal"  # default keeps the existing mission pipeline as owner


# ---------------------------------------------------------------------------
# Public queue API (used by endpoints + gateway)
# ---------------------------------------------------------------------------

class CodeTaskSpec:
    """Validated machine-readable task body."""

    def __init__(self, task: Dict[str, Any]):
        self.task = task

    @property
    def id(self) -> str:
        return self.task["id"]


def enqueue_task(*, title: str, prompt: str, routing: str = "auto",
                 priority: int = 50, depends_on: Optional[List[str]] = None,
                 steps: Optional[List[Dict[str, Any]]] = None,
                 tests: Optional[List[str]] = None,
                 acceptance: Optional[List[str]] = None,
                 scope: Optional[List[str]] = None,
                 unreal_prompt: Optional[str] = None) -> Dict[str, Any]:
    """Add a task to the durable queue; returns the stored task dict."""
    _ensure_dirs()
    resolved_routing = classify_routing(prompt, routing if routing != "auto" else None)
    if resolved_routing == "unreal":
        raise HTTPException(
            status_code=409,
            detail=("UNREAL_ROUTING: this prompt is an Unreal/editor/content task; "
                    "it is owned by the mission pipeline - use start_task."),
        )
    steps = steps or []
    tests = tests or []
    acceptance = acceptance or []
    scope = scope or []
    if not steps and not tests and not acceptance:
        raise HTTPException(
            status_code=422,
            detail="CODE_TASK_SPEC_REQUIRED: a code task needs machine-readable "
                   "steps/tests/acceptance (natural-language-only prompts are "
                   "BLOCKED, not guessed).",
        )
    if resolved_routing == "mixed" and not unreal_prompt:
        raise HTTPException(
            status_code=422,
            detail="MIXED_REQUIRES_UNREAL_PROMPT: a mixed task needs an "
                   "unreal_prompt for its second (Unreal mission) stage, "
                   "executed after the code stage passes.",
        )
    created = time.time()
    task = {
        "id": "",
        "title": title or prompt[:80],
        "prompt": prompt,
        "routing": resolved_routing,
        "priority": int(priority or 50),
        "depends_on": list(depends_on or []),
        "steps": steps,
        "tests": tests,
        "acceptance": acceptance,
        "scope": scope,
        "unreal_prompt": unreal_prompt,
        "status": STATUS_QUEUED,
        "attempt": 0,
        "max_attempts": MAX_ATTEMPTS,
        "created_at": created,
        "updated_at": created,
        "started_at": None,
        "finished_at": None,
        "verdict": None,
        "result": None,
        "error": None,
        "evidence": [],
        "blocked_reason": None,
        "next_task_id": None,
    }

    def _add(data):
        task["id"] = _new_task_id(data)
        data["tasks"].append(task)
        return task

    return _mutate(_add)


def list_tasks(include_internal: bool = True) -> List[Dict[str, Any]]:
    with STATE_LOCK:
        return list(_load_state().get("tasks", []))


def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    with STATE_LOCK:
        for task in _load_state().get("tasks", []):
            if task["id"] == task_id:
                return task
    return None


def get_status_snapshot() -> Dict[str, Any]:
    with STATE_LOCK:
        data = _load_state()
        tasks = data.get("tasks", [])
        by_status: Dict[str, int] = {}
        for t in tasks:
            by_status[t["status"]] = by_status.get(t["status"], 0) + 1
        return {
            "queue_size": len(tasks),
            "by_status": by_status,
            "current_task_id": _current_task_id(),
            "loop_running": _is_loop_running(),
            "last_updated": data.get("updated_at"),
        }


def retry_task(task_id: str) -> Dict[str, Any]:
    """Re-queue a failed/blocked/cancelled task (bounded attempts)."""

    def _do(data):
        for task in data["tasks"]:
            if task["id"] == task_id:
                if task["status"] == STATUS_RUNNING:
                    raise HTTPException(409, "task is running")
                if task["attempt"] >= int(task.get("max_attempts", MAX_ATTEMPTS)) and \
                        task["status"] == STATUS_FAILED:
                    raise HTTPException(409, "max attempts reached for this task")
                task["status"] = STATUS_QUEUED
                task["verdict"] = None
                task["error"] = None
                task["blocked_reason"] = None
                task["result"] = None
                task["cancel_requested"] = False
                task["finished_at"] = None
                task["updated_at"] = time.time()
                return task
        raise HTTPException(404, f"task {task_id} not found")

    return _mutate(_do)


def cancel_task(task_id: str) -> Dict[str, Any]:
    def _do(data):
        for task in data["tasks"]:
            if task["id"] == task_id:
                if task["status"] in TERMINAL:
                    raise HTTPException(409, "task already finished")
                task["status"] = STATUS_CANCELLED
                task["verdict"] = "CANCELLED"
                task["finished_at"] = time.time()
                task["updated_at"] = time.time()
                task["error"] = "cancelled by request"
                task["cancel_requested"] = True  # worker honours at phase bounds
                return task
        raise HTTPException(404, f"task {task_id} not found")

    return _mutate(_do)


def _is_dep_satisfied(task: Dict[str, Any], dep_id: str) -> bool:
    dep = get_task(dep_id)
    if dep is None:
        return False
    return dep["status"] in (STATUS_PASSED, STATUS_CANCELLED)


def _eligible_tasks() -> List[Dict[str, Any]]:
    """queued tasks whose dependencies are satisfied; highest priority first."""
    with STATE_LOCK:
        tasks = _load_state().get("tasks", [])
    ready = []
    for task in tasks:
        if task["status"] != STATUS_QUEUED:
            continue
        deps = task.get("depends_on") or []
        if not all(_is_dep_satisfied(task, d) for d in deps):
            continue
        ready.append(task)
    ready.sort(key=lambda t: (-int(t.get("priority", 50)), t.get("created_at", 0)))
    return ready


def _current_task_id() -> Optional[str]:
    with STATE_LOCK:
        for task in _load_state().get("tasks", []):
            if task["status"] == STATUS_RUNNING:
                return task["id"]
    return None


def _is_loop_running() -> bool:
    global _RUNNING_LOOP
    return bool(_RUNNING_LOOP)


# ---------------------------------------------------------------------------
# Worker internals
# ---------------------------------------------------------------------------

def _run_git(args: List[str], cwd: Path, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        timeout=timeout, encoding="utf-8", errors="replace",
    )


def _venv_python() -> str:
    if VENV_PYTHON.exists():
        return str(VENV_PYTHON)
    return sys.executable


def _path_in_allowed_roots(rel: str) -> bool:
    top = str(rel).replace("\\", "/").split("/", 1)[0]
    return top in ALLOWED_ROOTS and not str(rel).startswith(("__pycache__", ".", "memory/"))


def _mark(task_id: str, **fields) -> Dict[str, Any]:
    def _do(data):
        for task in data["tasks"]:
            if task["id"] == task_id:
                task.update(fields)
                task["updated_at"] = time.time()
                return task
        raise HTTPException(404, f"task {task_id} not found")

    return _mutate(_do)


def _finish(task_id: str, status: str, verdict: str, *, result=None,
            error: Optional[str] = None, evidence: Optional[List[str]] = None,
            blocked_reason: Optional[str] = None) -> Dict[str, Any]:
    return _mark(
        task_id,
        status=status,
        verdict=verdict,
        result=result,
        error=error,
        evidence=list(evidence or []),
        blocked_reason=blocked_reason,
        finished_at=time.time(),
    )


# --- isolated worktree lifecycle --------------------------------------------

def _create_worktree(task_id: str) -> tuple[Path, str]:
    """Create an isolated branch + worktree from committed HEAD.

    Returns (worktree_dir, branch). Raises RuntimeError on failure.
    """
    _ensure_dirs()
    branch = f"aivido/code-task/{task_id}"
    wt_dir = WORKTREES_DIR / task_id
    # Clean leftovers from a previous attempt of the SAME task id: every
    # attempt must start from a fresh, clean HEAD baseline (retry semantics),
    # never from the stale state of an earlier attempt.
    if wt_dir.exists():
        shutil.rmtree(wt_dir, ignore_errors=True)
    _run_git(["worktree", "prune"], ROOT)
    result = _run_git(["worktree", "add", "-b", branch, str(wt_dir), "HEAD"], ROOT)
    if result.returncode != 0:
        # branch already exists from a previous attempt -> remove and retry
        _run_git(["branch", "-D", branch], ROOT)
        _run_git(["worktree", "prune"], ROOT)
        result = _run_git(
            ["worktree", "add", "-b", branch, str(wt_dir), "HEAD"], ROOT)
        if result.returncode != 0:
            raise RuntimeError(
                f"worktree add failed: {(result.stderr or result.stdout).strip()}")
    return wt_dir, branch


def _remove_worktree(wt_dir: Path) -> None:
    if not wt_dir.exists():
        return
    _run_git(["worktree", "remove", "--force", str(wt_dir)], ROOT, timeout=120)
    if wt_dir.exists():
        shutil.rmtree(wt_dir, ignore_errors=True)


def _worktree_changed_files(wt_dir: Path) -> List[str]:
    result = _run_git(
        ["status", "--porcelain", "--untracked-files=all"], wt_dir, timeout=60)
    files = []
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        rel = line[3:].strip().replace("\\", "/")
        if "->" in rel:
            rel = rel.split("->")[1].strip()
        if "__pycache__" in rel:
            continue
        files.append(rel)
    return files


def _commit_isolated(task_id: str, title: str, wt_dir: Path) -> Optional[str]:
    """Commit all scoped changes on the isolated branch; returns commit hash."""
    result = _run_git(["add", "-A"], wt_dir)
    if result.returncode != 0:
        return None
    msg = f"code-task {task_id}: {title[:80]}".replace("\n", " ")
    result = _run_git(
        ["-c", "user.name=Aivido Code Worker",
         "-c", "user.email=code.worker@aivido.local",
         "commit", "-m", msg,
         "--author=Aivido Code Worker <code.worker@aivido.local>"],
        wt_dir)
    if result.returncode != 0:
        return None
    # Real hash comes from rev-parse, not git-commit summary output.
    rev = _run_git(["rev-parse", "HEAD"], wt_dir, timeout=30)
    if rev.returncode == 0 and rev.stdout.strip():
        return rev.stdout.strip().splitlines()[0].strip()
    return None


def _write_evidence(task_id: str, payload: Dict[str, Any]) -> str:
    ev_dir = EVIDENCE_DIR / task_id
    ev_dir.mkdir(parents=True, exist_ok=True)
    path = ev_dir / "evidence.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(path)


# --- code stage executor ----------------------------------------------------

def execute_code_stage(task: Dict[str, Any]) -> Dict[str, Any]:
    """Run the machine-readable steps in an isolated worktree.

    Deterministic contract:
      steps:      [{"op": "create_file", "path": "<rel>", "content": "<text>"}]
      tests:      ["pytest <rel-file>", "py_compile <rel-file>"]
      acceptance: ["exists <rel-file>", "contains <rel-file>|<substring>"]
      scope:      [rel paths allowed to change] (optional; derived if absent)

    Returns {"ok": bool, "verdict": PASS|FAIL|BLOCKED, "error": str|None,
             "evidence": {...}} — never invents PASS.
    """
    task_id = task["id"]
    steps = task.get("steps") or []
    tests = task.get("tests") or []
    acceptance = task.get("acceptance") or []
    declared_scope = [str(s).replace("\\", "/") for s in (task.get("scope") or [])]

    # ---- validation before touching git
    planned_paths = []
    for step in steps:
        op = step.get("op")
        rel = str(step.get("path") or "").replace("\\", "/")
        if op != "create_file":
            return {"ok": False, "verdict": "BLOCKED",
                    "error": f"unsupported op '{op}' (only create_file in v1)"}
        if not rel or not _path_in_allowed_roots(rel):
            return {"ok": False, "verdict": "BLOCKED",
                    "error": f"path '{rel}' outside allowed roots {ALLOWED_ROOTS}"}
        planned_paths.append(rel)
    if declared_scope:
        outside = [p for p in planned_paths
                   if p not in declared_scope and not p.startswith(("__pycache__",))]
        if outside:
            return {"ok": False, "verdict": "BLOCKED",
                    "error": f"planned paths {outside} not inside declared scope"}
    scope = declared_scope or planned_paths

    try:
        wt_dir, branch = _create_worktree(task_id)
    except RuntimeError as exc:
        return {"ok": False, "verdict": "FAIL", "error": str(exc)}

    evidence: Dict[str, Any] = {"task_id": task_id, "branch": branch,
                                "worktree": str(wt_dir), "logs": {}}
    try:
        # Refuse to touch anything that already exists in the live main tree
        # (tracked at HEAD or present untracked) — new files only, no clobber.
        for rel in planned_paths:
            live = ROOT / rel.replace("/", os.sep)
            wt_file = wt_dir / rel.replace("/", os.sep)
            if wt_file.exists():
                return {"ok": False, "verdict": "BLOCKED",
                        "error": f"{rel} already exists in the baseline snapshot"}
            if live.exists():
                return {"ok": False, "verdict": "BLOCKED",
                        "error": f"{rel} already exists in the live main tree "
                                 f"(refusing to diverge from uncommitted work)"}

        # 1) apply steps
        for step in steps:
            rel = str(step["path"]).replace("\\", "/")
            target = wt_dir / rel.replace("/", os.sep)
            target.parent.mkdir(parents=True, exist_ok=True)
            content = str(step.get("content") or "")
            target.write_text(content, encoding="utf-8")

        # 2) run requested tests / compile checks
        checks = []
        for spec in tests:
            spec = spec.strip()
            tag = spec.replace(" ", "_")[:60]
            out = _run_in_worktree(wt_dir, spec)
            checks.append({"command": spec, "exit": out.returncode,
                           "ok": out.returncode == 0,
                           "log": out.stdout[-4000:] + out.stderr[-4000:]})
            evidence["logs"][tag] = out.stdout[-4000:] + out.stderr[-4000:]
        tests_ok = all(c["ok"] for c in checks)

        # 3) acceptance checks
        accept = []
        for cond in acceptance:
            cond = cond.strip()
            ok = _check_acceptance(wt_dir, cond)
            accept.append({"condition": cond, "ok": ok})
        accept_ok = all(a["ok"] for a in accept)

        # 4) scope gate: changed files must be exactly the planned/declared set
        changed = _worktree_changed_files(wt_dir)
        changed_scope = [c for c in changed
                         if not c.startswith(("__pycache__",)) and c not in scope]
        scope_ok = not changed_scope and bool(changed or not steps)

        ok = bool(tests_ok and accept_ok and scope_ok)
        if not ok:
            return {"ok": False, "verdict": "FAIL",
                    "error": _first_failure(checks, accept, changed_scope),
                    "evidence": {**evidence, "checks": checks,
                                 "acceptance": accept,
                                 "changed_files": changed, "scope_ok": scope_ok}}

        # 5) commit ONLY verified scoped changes on the isolated branch
        commit_hash = _commit_isolated(task_id, task.get("title", task_id), wt_dir)
        if not commit_hash:
            return {"ok": False, "verdict": "FAIL",
                    "error": "verification passed but the isolated commit failed",
                    "evidence": {**evidence, "checks": checks,
                                 "acceptance": accept, "changed_files": changed}}

        patch = _run_git(["format-patch", "-1", "--stdout"], wt_dir)
        patch_path = EVIDENCE_DIR / task_id / "change.patch"
        patch_path.parent.mkdir(parents=True, exist_ok=True)
        patch_path.write_text(patch.stdout, encoding="utf-8")
        stat = _run_git(["show", "--stat", "--oneline", "HEAD"], wt_dir)

        return {"ok": True, "verdict": "PASS",
                "error": None,
                "evidence": {**evidence,
                             "commit": commit_hash,
                             "patch_file": str(patch_path),
                             "commit_stat": stat.stdout,
                             "checks": checks, "acceptance": accept,
                             "changed_files": changed}}
    finally:
        _remove_worktree(wt_dir)


def _run_in_worktree(wt_dir: Path, spec: str) -> subprocess.CompletedProcess:
    """Allow-listed commands run with the venv python inside the worktree."""
    parts = spec.split()
    cmd = parts[0] if parts else ""
    if cmd in ("pytest", "py_compile", "python", "-m"):
        argv = [_venv_python()]
        if cmd == "pytest":
            argv += ["-m", "pytest", "-p", "no:cacheprovider", "-q"]
            argv += [p for p in parts[1:] if not p.startswith("-")][:1]  # file only
        elif cmd == "py_compile":
            argv += ["-m", "py_compile"]
            argv += [p for p in parts[1:]][:1]
        else:
            argv += parts[1:]
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            return subprocess.run(argv, cwd=str(wt_dir), capture_output=True,
                                  text=True, timeout=420, encoding="utf-8",
                                  errors="replace", env=env)
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(argv, 124, "TIMEOUT", "TIMEOUT")
    return subprocess.CompletedProcess(["denied:" + cmd], 126, "", "command not allow-listed")


def _check_acceptance(wt_dir: Path, cond: str) -> bool:
    cond = cond.strip()
    if cond.startswith("exists "):
        rel = cond[len("exists "):].strip().replace("\\", "/")
        return (wt_dir / rel.replace("/", os.sep)).is_file()
    if cond.startswith("contains "):
        rest = cond[len("contains "):].strip()
        if "|" in rest:
            rel, _, needle = rest.partition("|")
        else:
            rel, needle = rest, ""
        try:
            content = (wt_dir / rel.strip().replace("/", os.sep)).read_text(encoding="utf-8")
        except Exception:
            return False
        return needle in content
    if cond.startswith("imports "):
        mod = cond[len("imports "):].strip()
        try:
            __import__(mod)
            return True
        except Exception:
            return False
    return False


def run_unreal_stage(prompt: str, task_id: str = "",
                     timeout_minutes: int = 20) -> Dict[str, Any]:
    """Mixed-task stage 2: dispatch one prompt to the EXISTING Unreal mission
    pipeline (POST /api/unreal-coder/async) and poll its real checkpoint.

    Never fabricates PASS: the stage passes only when the mission pipeline
    itself reports a SUCCESS/PASS verdict; its real verdict is otherwise
    reported back (and the mixed task then FAILs honestly).
    """
    import requests as _requests
    base = BACKEND_URL.rstrip("/")
    try:
        r = _requests.post(base + "/api/unreal-coder/async",
                           json={"prompt": str(prompt or "").strip()},
                           timeout=30)
        r.raise_for_status()
        body = r.json()
    except Exception as exc:
        return {"ok": False, "error": f"unreal stage dispatch failed: {exc}"}
    mission_id = str(body.get("mission_id") or "")
    if not mission_id:
        return {"ok": False, "error": "unreal stage returned no mission_id"}
    deadline = time.time() + timeout_minutes * 60
    while time.time() < deadline:
        try:
            m = _requests.get(base + f"/api/unreal-coder/mission/{mission_id}",
                              timeout=30)
            m.raise_for_status()
            payload = m.json()
        except Exception as exc:
            time.sleep(10)
            continue
        status = str(payload.get("status") or "")
        verdict = str(payload.get("verdict") or "")
        if status in ("complete", "failed", "blocked", "cancelled"):
            ok = status == "complete" and verdict.upper() in ("SUCCESS", "PASS")
            return {"ok": ok, "mission_id": mission_id,
                    "status": status, "verdict": verdict,
                    "why": payload.get("why"),
                    "error": None if ok else (
                        f"unreal stage ended {status} verdict={verdict}")}
        time.sleep(10)
    return {"ok": False, "mission_id": mission_id,
            "error": "unreal stage timed out after %d minutes" % timeout_minutes}


def _first_failure(checks, accept, changed_scope) -> str:
    for c in checks:
        if not c.get("ok"):
            return f"test/check failed: {c.get('command')}"
    for a in accept:
        if not a.get("ok"):
            return f"acceptance failed: {a.get('condition')}"
    if changed_scope:
        return f"scope violation: changed files outside declared scope {changed_scope}"
    return "unknown failure"


# --- task orchestration ------------------------------------------------------

def _is_cancelled(task_id: str) -> bool:
    task = get_task(task_id)
    return bool(task and task.get("status") == STATUS_CANCELLED)


def _run_task(task_id: str) -> None:
    """Run one task to a terminal state (single-flight from the loop)."""
    task = get_task(task_id)
    if task is None or task["status"] != STATUS_QUEUED:
        return
    _mark(task_id, status=STATUS_RUNNING, started_at=time.time())
    if _is_cancelled(task_id):
        return  # cancel arrived between selection and start
    task = get_task(task_id)
    _mark(task_id, attempt=int(task.get("attempt", 0)) + 1)
    if _is_cancelled(task_id):
        return
    task = get_task(task_id)
    routing = task.get("routing", "code")

    result = None
    error = None
    evidence: List[str] = []
    if routing in ("code", "mixed"):
        # Stage 1 (dependency order): code/repo work in the isolated worktree.
        outcome = execute_code_stage(task)
        if _is_cancelled(task_id):
            return  # cancel is authoritative: never PASS after cancellation
        if not outcome.get("ok"):
            verdict = outcome.get("verdict", "FAIL")
            error = outcome.get("error")
            if verdict == "BLOCKED":
                _write_evidence(task_id, {"task_id": task_id,
                                          "title": task.get("title"),
                                          "verdict": "BLOCKED",
                                          "reason": error})
                _finish(task_id, STATUS_BLOCKED, "BLOCKED", error=error,
                        blocked_reason=error)
            else:
                _write_evidence(task_id, {"task_id": task_id,
                                          "title": task.get("title"),
                                          "verdict": "FAIL",
                                          "error": error})
                _finish(task_id, STATUS_FAILED, "FAIL", error=error)
            return
        ev = outcome.get("evidence") or {}
        patch_file = ev.get("patch_file")
        ev_path = _write_evidence(task_id, {
            "task_id": task_id, "title": task.get("title"),
            "prompt": task.get("prompt"),
            "verdict": outcome.get("verdict"),
            "commit": ev.get("commit"),
            "branch": ev.get("branch"),
            "checks": ev.get("checks"),
            "acceptance": ev.get("acceptance"),
            "changed_files": ev.get("changed_files"),
            "commit_stat": ev.get("commit_stat"),
        })
        evidence = [ev_path]
        if patch_file and Path(patch_file).exists():
            evidence.append(patch_file)
        result: Dict[str, Any] = {
            "summary": f"code stage completed: {len(ev.get('checks') or [])} "
                       f"checks, {len(ev.get('acceptance') or [])} acceptance "
                       f"conditions, commit {ev.get('commit')}",
            "branch": ev.get("branch"),
            "commit": ev.get("commit"),
            "evidence_files": evidence,
        }
        # Stage 2 (mixed only): run the Unreal mission AFTER the code stage
        # passed, in dependency order, through the existing mission pipeline.
        if routing == "mixed":
            unreal = run_unreal_stage(str(task.get("unreal_prompt") or ""), task_id)
            if _is_cancelled(task_id):
                return
            result["unreal_stage"] = unreal
            if not unreal.get("ok"):
                _write_evidence(task_id, {"task_id": task_id,
                                          "title": task.get("title"),
                                          "stage": "unreal",
                                          "verdict": "FAIL",
                                          "unreal_stage": unreal})
                _finish(task_id, STATUS_FAILED, "FAIL",
                        error=unreal.get("error"), evidence=evidence)
                return
            result["summary"] += (
                f" | unreal stage PASSED (mission {unreal.get('mission_id')})")
        _finish(task_id, STATUS_PASSED, "PASS", result=result, evidence=evidence)
    else:  # pragma: no cover - defensive; enqueue rejects pure-unreal
        _finish(task_id, STATUS_BLOCKED, "BLOCKED",
                error="task without an executable stage is not supported",
                blocked_reason="route pure-unreal tasks via start_task")


def _auto_retry_or_advance(task_id: str) -> None:
    """After a terminal task, auto-advance to the next eligible task.

    Failed tasks are auto-retried up to max_attempts (requirement 6);
    blocked tasks stay BLOCKED (requirement 7) and the loop continues with
    another independent eligible task.
    """
    task = get_task(task_id)
    if task is None:
        return
    if task["status"] == STATUS_FAILED and task["attempt"] < int(task.get("max_attempts", MAX_ATTEMPTS)):
        retry_task(task_id)
    # PASS/BLOCKED/CANCELLED: the outer worker loop re-picks the next
    # eligible task automatically (blocked tasks are simply not eligible).


def _run_loop_once() -> None:
    """Execute the single highest-priority eligible task, then advance."""
    task = _eligible_tasks()
    if not task:
        return
    task = task[0]
    if task["status"] != STATUS_QUEUED:
        return
    _run_task(task["id"])
    _auto_retry_or_advance(task["id"])


def _run_worker_loop() -> None:
    """Background loop: keep executing eligible tasks until none remain."""
    global _RUNNING_LOOP
    _RUNNING_LOOP = True
    try:
        while _eligible_tasks():
            # skip BLOCKED/FAILED (not eligible) automatically; queue advances
            try:
                _run_loop_once()
            except Exception as exc:  # never let one task kill the loop
                log_line = f"worker loop error: {exc}"
                if _current_task_id():
                    _mark(_current_task_id(), status=STATUS_FAILED,
                          verdict="FAIL", error=log_line, finished_at=time.time())
                time.sleep(2)
    finally:
        _RUNNING_LOOP = False


def start_worker_loop() -> bool:
    """Start the single-flight loop if eligible work exists and no loop runs."""
    global _RUNNER_THREAD
    with STATE_LOCK:
        if _RUNNING_LOOP:
            return True
        if not _eligible_tasks():
            return False
        _RUNNER_THREAD = threading.Thread(
            target=_run_worker_loop, name="code-task-worker", daemon=True)
        _RUNNER_THREAD.start()
        return True


def _watchdog() -> None:
    while True:
        try:
            if not _RUNNING_LOOP:
                start_worker_loop()
        except Exception:
            pass
        time.sleep(WATCHDOG_INTERVAL_S)


def startup_recovery() -> None:
    """Durable recovery: interrupted 'running' tasks return to the queue."""
    with STATE_LOCK:
        data = _load_state()
        changed = False
        for task in data.get("tasks", []):
            if task["status"] == STATUS_RUNNING:
                task["status"] = STATUS_QUEUED
                task["error"] = (task.get("error") or "") + " (interrupted; resumed)"
                changed = True
        if changed:
            _save_state(data)
    start_code_supervisor()


def start_code_supervisor() -> None:
    """Idempotent watchdog start (called from backend startup + endpoints)."""
    _ensure_dirs()
    if not getattr(start_code_supervisor, "_started", False):
        start_code_supervisor._started = True
        threading.Thread(target=_watchdog, name="code-task-watchdog",
                         daemon=True).start()
    start_worker_loop()


# ---------------------------------------------------------------------------
# Evidence retrieval
# ---------------------------------------------------------------------------

def get_evidence(task_id: str) -> Dict[str, Any]:
    task = get_task(task_id)
    if task is None:
        raise HTTPException(404, f"task {task_id} not found")
    bundle = {
        "task_id": task_id,
        "title": task.get("title"),
        "status": task.get("status"),
        "verdict": task.get("verdict"),
        "error": task.get("error"),
        "blocked_reason": task.get("blocked_reason"),
        "result": task.get("result"),
        "evidence_files": list(task.get("evidence") or []),
        "files": {},
    }
    ev_dir = EVIDENCE_DIR / task_id
    if ev_dir.exists():
        for f in sorted(ev_dir.iterdir()):
            try:
                bundle["files"][f.name] = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass
    return bundle


# ---------------------------------------------------------------------------
# FastAPI router
# ---------------------------------------------------------------------------

class EnqueueRequest(BaseModel):
    title: str = ""
    prompt: str
    routing: str = "auto"
    priority: int = 50
    depends_on: Optional[List[str]] = None
    steps: Optional[List[Dict[str, Any]]] = None
    tests: Optional[List[str]] = None
    acceptance: Optional[List[str]] = None
    scope: Optional[List[str]] = None
    unreal_prompt: Optional[str] = None


class ClassifyRequest(BaseModel):
    prompt: str


if APIRouter is not None:
    router = APIRouter(prefix="/api/code")

    @router.post("/tasks")
    def api_enqueue(req: EnqueueRequest):
        task = enqueue_task(
            title=req.title, prompt=req.prompt, routing=req.routing,
            priority=req.priority, depends_on=req.depends_on,
            steps=req.steps, tests=req.tests, acceptance=req.acceptance,
            scope=req.scope, unreal_prompt=req.unreal_prompt)
        start_code_supervisor()
        return {"ok": True, "task": task}

    @router.get("/tasks")
    def api_list():
        return {"ok": True, "tasks": list_tasks(),
                "snapshot": get_status_snapshot()}

    @router.get("/tasks/{task_id}")
    def api_get(task_id: str):
        task = get_task(task_id)
        if task is None:
            raise HTTPException(404, f"task {task_id} not found")
        return {"ok": True, "task": task}

    @router.post("/tasks/{task_id}/retry")
    def api_retry(task_id: str):
        task = retry_task(task_id)
        start_code_supervisor()
        return {"ok": True, "task": task}

    @router.post("/tasks/{task_id}/cancel")
    def api_cancel(task_id: str):
        return {"ok": True, "task": cancel_task(task_id)}

    @router.get("/tasks/{task_id}/evidence")
    def api_evidence(task_id: str):
        return {"ok": True, "evidence": get_evidence(task_id)}

    @router.post("/classify")
    def api_classify(req: ClassifyRequest):
        return {"ok": True, "routing": classify_routing(req.prompt)}

    @router.get("/status")
    def api_status():
        return {"ok": True, "snapshot": get_status_snapshot()}
else:  # pragma: no cover
    router = None
