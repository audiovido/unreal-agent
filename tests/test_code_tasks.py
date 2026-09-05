"""CODE TASKS SUPERVISOR — hermetic tests (executor faked; no git, no live editor).

Covers the autonomous supervisor contract that the MCP code tools expose:
  - routing classifier (code / unreal / mixed)
  - queue semantics (priority, dependencies, auto-advance)
  - verdict honesty via the evidence gate (PASS only on ok + evidence)
  - true blockers -> BLOCKED evidence, loop continues with another task
  - bounded auto-retry on FAIL, then terminal FAIL
  - cancel; durable recovery (running -> queued) after a crash
  - single-flight worker loop
"""
import sys
import time
from pathlib import Path

import threading

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.code_tasks as ct  # noqa: E402


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    d = tmp_path / "state"
    monkeypatch.setattr(ct, "STATE_DIR", d)
    monkeypatch.setattr(ct, "STATE_FILE", d / "state.json")
    monkeypatch.setattr(ct, "WORKTREES_DIR", d / "worktrees")
    monkeypatch.setattr(ct, "EVIDENCE_DIR", d / "evidence")
    ct._RUNNING_LOOP = False
    ct.start_code_supervisor._started = True  # keep the watchdog thread out of unit tests
    yield
    ct._RUNNING_LOOP = False


def _prompt(n=1):
    return f"create a new repo file app/code_worker_demo_{n}.py and its test"


def _steps(n=1):
    return [{"op": "create_file",
             "path": f"app/code_worker_demo_{n}.py",
             "content": f"def hello_{n}():\n    return {n}\n"}]


def _tests(n=1):
    return [f"py_compile app/code_worker_demo_{n}.py"]


def _acceptance(n=1):
    return [f"exists app/code_worker_demo_{n}.py",
            f"contains app/code_worker_demo_{n}.py|def hello_{n}"]


def _enqueue(n=1, **kw):
    return ct.enqueue_task(
        title=f"demo {n}", prompt=_prompt(n), routing="code",
        steps=_steps(n), tests=_tests(n), acceptance=_acceptance(n), **kw)


def _settle(timeout=6.0):
    ct.start_worker_loop()
    deadline = time.time() + timeout
    while time.time() < deadline:
        tasks = ct.list_tasks()
        if all(t["status"] in ct.TERMINAL for t in tasks) and not ct._RUNNING_LOOP:
            break
        time.sleep(0.05)
    return ct.list_tasks()


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def test_classify_routing():
    assert ct.classify_routing("fix the login bug in app/api.py and add a test") == "code"
    assert ct.classify_routing("cleanup unused imports and run pytest") == "code"
    assert ct.classify_routing("open the showcase level and render the camera shot") == "unreal"
    assert ct.classify_routing("refactor this module file and add tests, then open unreal to verify") == "mixed"
    assert ct.classify_routing("any prompt", "code") == "code"
    assert ct.classify_routing("any prompt", "unreal") == "unreal"


def test_enqueue_routes_unreal_away():
    with pytest.raises(Exception):
        ct.enqueue_task(title="u", prompt="open unreal level and add an actor",
                        routing="auto", steps=[{"op": "create_file",
                                                "path": "docs/x.md",
                                                "content": "x"}])


def test_enqueue_requires_machine_spec():
    with pytest.raises(Exception):
        ct.enqueue_task(title="bare", prompt="please clean up the repo",
                        routing="code")


# ---------------------------------------------------------------------------
# Queue: priority + dependency + auto-advance
# ---------------------------------------------------------------------------

def test_priority_order_and_auto_advance(monkeypatch):
    order = []
    calls = []

    def fake(task):
        order.append(task["id"])
        calls.append(task["id"])
        return {"ok": True, "verdict": "PASS",
                "evidence": {"commit": "abc123", "branch": "aivido/code-task/x",
                             "checks": [], "acceptance": [], "changed_files": [],
                             "patch_file": None}}

    monkeypatch.setattr(ct, "execute_code_stage", fake)
    low = _enqueue(1, priority=10)
    high = _enqueue(2, priority=100)
    tasks = _settle()
    by_id = {t["id"]: t for t in tasks}
    assert [t["id"] for t in tasks] == [low["id"], high["id"]]
    assert order == [high["id"], low["id"]]  # priority first, then auto-advance
    assert all(by_id[t]["status"] == ct.STATUS_PASSED and by_id[t]["verdict"] == "PASS"
               for t in (low["id"], high["id"]))
    assert calls == [high["id"], low["id"]]  # each executed exactly once


def test_dependency_blocks_until_ready(monkeypatch):
    order = []

    def fake(task):
        order.append(task["id"])
        return {"ok": True, "verdict": "PASS",
                "evidence": {"commit": "c", "branch": "b", "checks": [],
                             "acceptance": [], "changed_files": [],
                             "patch_file": None}}

    monkeypatch.setattr(ct, "execute_code_stage", fake)
    dep = _enqueue(1)
    child = _enqueue(2, depends_on=[dep["id"]])
    tasks = _settle()
    by_id = {t["id"]: t for t in tasks}
    assert order == [dep["id"], child["id"]]
    assert by_id[child["id"]]["status"] == ct.STATUS_PASSED


# ---------------------------------------------------------------------------
# Evidence gate / blocker / retry / cancel
# ---------------------------------------------------------------------------

def test_blocker_writes_evidence_and_loop_continues(monkeypatch):
    outcomes = [{"ok": False, "verdict": "BLOCKED",
                 "error": "path outside allowed roots"},
                {"ok": True, "verdict": "PASS",
                 "evidence": {"commit": "c", "branch": "b", "checks": [],
                              "acceptance": [], "changed_files": [],
                              "patch_file": None}}]

    def fake(task):
        return outcomes.pop(0)

    monkeypatch.setattr(ct, "execute_code_stage", fake)
    a = _enqueue(1)
    b = _enqueue(2)
    tasks = _settle()
    by_id = {t["id"]: t for t in tasks}
    assert by_id[a["id"]]["status"] == ct.STATUS_BLOCKED
    assert by_id[a["id"]]["verdict"] == "BLOCKED"
    assert by_id[a["id"]]["blocked_reason"] == "path outside allowed roots"
    assert by_id[b["id"]]["status"] == ct.STATUS_PASSED
    # BLOCKED evidence file written durably
    assert (ct.EVIDENCE_DIR / a["id"] / "evidence.json").exists()


def test_failure_auto_retries_then_fails_terminal(monkeypatch):
    calls = []

    def fake(task):
        calls.append(task["id"])
        return {"ok": False, "verdict": "FAIL", "error": "check failed"}

    monkeypatch.setattr(ct, "execute_code_stage", fake)
    monkeypatch.setattr(ct, "MAX_ATTEMPTS", 2)
    task = _enqueue(1)
    tasks = _settle(timeout=8.0)
    by_id = {t["id"]: t for t in tasks}
    final = by_id[task["id"]]
    assert final["status"] == ct.STATUS_FAILED
    assert final["verdict"] == "FAIL"
    assert final["attempt"] == 2  # bounded retries, no infinite loop
    assert calls == [task["id"]] * 2


def test_cancel_queued_task(monkeypatch):
    def fake(task):
        return {"ok": True, "verdict": "PASS",
                "evidence": {"commit": "c", "branch": "b", "checks": [],
                             "acceptance": [], "changed_files": [],
                             "patch_file": None}}

    monkeypatch.setattr(ct, "execute_code_stage", fake)
    task = _enqueue(1)
    cancelled = ct.cancel_task(task["id"])
    assert cancelled["status"] == ct.STATUS_CANCELLED
    tasks = _settle(timeout=2.0)
    assert tasks[0]["status"] == ct.STATUS_CANCELLED


def test_cancel_while_running_is_authoritative(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def fake(task):
        started.set()
        release.wait(timeout=5)
        return {"ok": True, "verdict": "PASS",
                "evidence": {"commit": "c", "branch": "b", "checks": [],
                             "acceptance": [], "changed_files": [],
                             "patch_file": None}}

    monkeypatch.setattr(ct, "execute_code_stage", fake)
    task = _enqueue(1)
    ct.start_worker_loop()
    assert started.wait(timeout=5)
    cancelled = ct.cancel_task(task["id"])
    assert cancelled["status"] == ct.STATUS_CANCELLED
    release.set()  # let the worker finish its (now-cancelled) stage
    deadline = time.time() + 5
    while time.time() < deadline and ct._RUNNING_LOOP:
        time.sleep(0.05)
    final = ct.get_task(task["id"])
    assert final["status"] == ct.STATUS_CANCELLED
    assert final["verdict"] == "CANCELLED"  # never overridden by the worker's PASS


def test_retry_blocked_task(monkeypatch):
    state = {"fail_first": True}

    def fake(task):
        if state["fail_first"]:
            state["fail_first"] = False
            return {"ok": False, "verdict": "BLOCKED", "error": "transient"}
        return {"ok": True, "verdict": "PASS",
                "evidence": {"commit": "c", "branch": "b", "checks": [],
                             "acceptance": [], "changed_files": [],
                             "patch_file": None}}

    monkeypatch.setattr(ct, "execute_code_stage", fake)
    task = _enqueue(1)
    tasks = _settle(timeout=4.0)
    assert tasks[0]["status"] == ct.STATUS_BLOCKED
    ct.retry_task(task["id"])
    tasks = _settle(timeout=4.0)
    assert tasks[0]["status"] == ct.STATUS_PASSED
    assert tasks[0]["verdict"] == "PASS"


# ---------------------------------------------------------------------------
# Recovery + single-flight
# ---------------------------------------------------------------------------

def test_recovery_resumes_interrupted_running_task(monkeypatch):
    monkeypatch.setattr(ct, "start_code_supervisor", lambda: None)
    task = _enqueue(1)
    ct._mark(task["id"], status=ct.STATUS_RUNNING)  # simulate crash mid-run
    ct.startup_recovery()
    revived = ct.get_task(task["id"])
    assert revived["status"] == ct.STATUS_QUEUED


def test_mixed_task_runs_code_then_unreal_in_order(monkeypatch):
    order = []

    def fake_code(task):
        order.append("code")
        return {"ok": True, "verdict": "PASS",
                "evidence": {"commit": "c", "branch": "b", "checks": [],
                             "acceptance": [], "changed_files": [],
                             "patch_file": None}}

    def fake_unreal(prompt, task_id=""):
        order.append("unreal")
        assert task_id  # code stage evidence must exist before stage 2
        return {"ok": True, "mission_id": "m1", "verdict": "SUCCESS",
                "status": "complete", "error": None}

    monkeypatch.setattr(ct, "execute_code_stage", fake_code)
    monkeypatch.setattr(ct, "run_unreal_stage", fake_unreal)
    task = ct.enqueue_task(
        title="mixed demo",
        prompt="refactor this module file and add a test, then open unreal to verify it",
        routing="auto",
        steps=[{"op": "create_file", "path": "docs/mixed_probe.md",
                "content": "x"}],
        tests=[],
        acceptance=["exists docs/mixed_probe.md"],
        unreal_prompt="verify the module renders in the showcase level")
    assert task["routing"] == "mixed"
    tasks = _settle(timeout=8.0)
    final = tasks[0]
    assert final["status"] == ct.STATUS_PASSED
    assert final["verdict"] == "PASS"
    assert order == ["code", "unreal"]  # dependency order preserved
    res = final.get("result") or {}
    assert (res.get("unreal_stage") or {}).get("mission_id") == "m1"


def test_worker_is_single_flight(monkeypatch):
    calls = []

    def fake(task):
        calls.append(task["id"])
        time.sleep(0.1)
        return {"ok": True, "verdict": "PASS",
                "evidence": {"commit": "c", "branch": "b", "checks": [],
                             "acceptance": [], "changed_files": [],
                             "patch_file": None}}

    monkeypatch.setattr(ct, "execute_code_stage", fake)
    for i in range(4):
        _enqueue(i)
    tasks = _settle(timeout=8.0)
    assert len(calls) == 4
    assert all(t["status"] == ct.STATUS_PASSED for t in tasks)
