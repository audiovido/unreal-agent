from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from yodaw.commands import CommandRequest, run_local
from yodaw.git import integrate, push_current
from yodaw.missions import MissionStore
from yodaw.orchestrator import MissionOrchestrator
from yodaw.plan import WorkerPlan, plan_from_request, validate_plan
from yodaw.retry import RetryEngine, ValidationEvidence
from yodaw.targets import SSHAdapter, build_targets
from yodaw.workspaces import WorkspaceManager


def git(repo: Path, *args: str):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"; repo.mkdir(parents=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("base\n")
    git(repo, "add", "."); git(repo, "commit", "-qm", "base")
    return repo


def test_command_engine_timeout_and_result(tmp_path):
    result = run_local(CommandRequest(cwd=str(tmp_path), allowed_root=str(tmp_path), command=["python", "-c", "print('ok')"], timeout=5))
    assert result.exit_code == 0 and result.stdout.strip() == "ok" and not result.timed_out
    timeout = run_local(CommandRequest(cwd=str(tmp_path), allowed_root=str(tmp_path), command=["python", "-c", "import time; time.sleep(2)"], timeout=.05))
    assert timeout.exit_code == 124 and timeout.timed_out


def test_workspace_create_reuse_dirty_protection_and_cleanup(tmp_path):
    repo = make_repo(tmp_path); manager = WorkspaceManager(tmp_path / "state")
    first = manager.create_workspace("m1", str(repo)); second = manager.create_workspace("m1", str(repo))
    assert first.path == second.path and Path(first.path).is_dir()
    Path(first.path, "dirty.txt").write_text("keep")
    with pytest.raises(RuntimeError): manager.cleanup_worktree("m1")
    assert manager.cleanup_worktree("m1", force=True) and manager.get("m1") is None


def test_retry_records_failure_then_corrective_pass_and_restore_on_exhaustion():
    def validate(plan, attempt):
        if attempt == 1: return ValidationEvidence("pytest", 1, stderr="assert failed", changed_files=["app/x.py"], plan_summary="initial")
        return ValidationEvidence("pytest", 0, stdout="1 passed", changed_files=["app/x.py"], plan_summary=str(plan))
    report = RetryEngine(2).run(initial_plan={"initial": True}, stage=lambda p, a: None, validate=validate, corrective_plan=lambda p, e, a: {"fix": a}, restore=lambda: None)
    assert report.passed and len(report.attempts) == 2 and report.attempts[0]["evidence"]["classification"] == "test_failure"
    restored = []
    report = RetryEngine(1).run(initial_plan={}, stage=lambda p, a: None, validate=lambda p, a: {"command": "pytest", "exit_code": 1, "stderr": "bad"}, corrective_plan=lambda p, e, a: p, restore=lambda: restored.append(True))
    assert not report.passed and restored == [True] and len(report.attempts) == 2


def test_target_adapters_are_configurable_without_credentials():
    targets = build_targets({"targets": {"local": {"type": "local"}, "shadow": {"type": "ssh", "host": "100.64.0.1", "user": "Shadow", "port": 2222, "identity_file": "~/.ssh/id"}}})
    assert isinstance(targets["shadow"], SSHAdapter) and targets["shadow"].config.identity_file == "~/.ssh/id"


def test_mission_state_persists_and_recovers(tmp_path):
    store = MissionStore(tmp_path / "state")
    mission = store.create("do work", str(tmp_path), state="RUNNING")
    assert store.get(mission.mission_id).state == "RUNNING"
    assert mission.mission_id in store.recover() and store.get(mission.mission_id).state == "RECOVERING"
    store.request_cancel(mission.mission_id); assert store.get(mission.mission_id).state == "CANCELLED"


def test_plan_rejects_overlapping_files_and_cycles():
    a = WorkerPlan("a", "a", ["a.py"], [{"op": "write_file", "path": "a.py", "content": "a"}], depends_on=["b"])
    b = WorkerPlan("b", "b", ["a.py"], [{"op": "write_file", "path": "a.py", "content": "b"}], depends_on=["a"])
    with pytest.raises(ValueError, match="same files"):
        validate_plan([a, b])
    b.files = ["b.py"]; b.steps = [{"op": "write_file", "path": "b.py", "content": "b"}]
    with pytest.raises(ValueError, match="cycle"):
        validate_plan([a, b])


def test_real_concurrent_mission_auto_corrects_and_integrates(tmp_path):
    repo = make_repo(tmp_path); state = tmp_path / "state"
    plan = plan_from_request("Create a small feature touching multiple files, introduce a test failure, correct it automatically, run tests, commit and push.")
    updates = []
    mission = MissionOrchestrator(workspace_manager=WorkspaceManager(state), max_workers=2, update=lambda **x: updates.append(x)).run(
        mission_id="m1", repo=str(repo), prompt="proof", raw_plan=[p.to_dict() for p in plan], auto_commit=True)
    assert mission["state"] == "PASS"
    assert {w["state"] for w in mission["workers"]} == {"PASS"}
    assert len({w["commit_sha"] for w in mission["workers"]}) == 2
    assert any(any((w.get("evidence") or [{}])[0].get("status") == "FAIL" for w in u.get("workers", [])) for u in updates if u.get("workers"))
    assert (repo / "feature.py").is_file() and (repo / "test_feature.py").is_file() and (repo / "FEATURE.md").is_file()
    assert subprocess.run(["python", "-m", "pytest", "-q", "test_feature.py"], cwd=repo, capture_output=True).returncode == 0


def test_git_refuses_dirty_base_and_no_remote(tmp_path):
    repo = make_repo(tmp_path); (repo / "unrelated.txt").write_text("do not stage")
    result = integrate(repo, "missing", "x")
    assert not result.ok and "dirty" in (result.error or "")
    clean = make_repo(tmp_path / "clean")
    pushed = push_current(clean)
    assert not pushed.ok and pushed.push_status == "no_remote"
