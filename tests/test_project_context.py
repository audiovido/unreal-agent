"""Deterministic tests for the Unreal Agent Durable Active Project Context core.

These tests must NOT talk to the live bridge or scan the real Desktop, so every
resolution source is monkeypatched to a controlled value. They cover:

  1. explicit project path resolves
  2. no path + persisted context resolves
  3. stale persisted path + live bridge context recovers
  4. backend restart retains context
  5. editor restart recovers context
  6. planner preserves an explicit .uproject path
  7. inspect_project does not repeat an identical missing-path call
  8. PROJECT_CONTEXT_MISSING triggers recovery before STALL
  9. unresolved context after 3 attempts produces a structured BLOCKED verdict
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from tools.unreal import project_context as pc
from tools.unreal import project_manager as pm


def _write_uproject(root: Path, name: str, engine="5.8"):
    proj = root / name
    proj.mkdir(parents=True, exist_ok=True)
    upath = proj / f"{name}.uproject"
    upath.write_text(
        json.dumps({"FileVersion": 3, "EngineAssociation": engine}, indent=2),
        encoding="utf-8",
    )
    return upath


@pytest.fixture()
def iso_context(tmp_path, monkeypatch):
    """Point the durable store at a tmp file and neutralise live sources."""
    monkeypatch.setattr(pc, "ACTIVE_CONTEXT_FILE", tmp_path / "ctx.json")
    monkeypatch.setattr(pc, "KNOWN_PROJECT_PATHS", [])
    monkeypatch.setattr(pc, "_bounded_search", lambda *a, **k: [])
    # Simulate no reachable editor: identity pull returns nothing.
    monkeypatch.setattr(pc, "_live_bridge_context", lambda bridge=None: {})
    # Avoid constructing a real bridge binding in the unit tests.
    def _no_bridge(*a, **k):
        return None
    monkeypatch.setattr(pm, "_query_bridge", _no_bridge)
    pc.clear_active_context()
    return pc.ACTIVE_CONTEXT_FILE


def test_explicit_project_path_resolves(tmp_path, iso_context):
    upath = _write_uproject(tmp_path, "RegressProj")
    r = pm.inspect_project(uproject_path=str(upath))
    assert r.get("ok") is True
    assert r.get("name") == "RegressProj"
    assert not r.get("code")
    assert pc.load_active_context().get("project_name") == "RegressProj"


def test_no_path_persisted_context_resolves(tmp_path, iso_context):
    upath = _write_uproject(tmp_path, "PersistedProj")
    pc.update_active_context(uproject_path=str(upath), project_name="PersistedProj")
    r = pm.inspect_project()  # NOTE: no path -> must not return "uproject not found"
    assert r.get("ok") is True
    assert r.get("uproject_path") == str(upath)
    assert r.get("source_of_truth") == "persisted"


def test_stale_persisted_path_live_bridge_recovers(tmp_path, iso_context, monkeypatch):
    # Persisted context points at a project that has been moved/deleted.
    stale = tmp_path / "Gone" / "Gone.uproject"
    pc.update_active_context(
        uproject_path=str(stale), project_name="Gone", source_of_truth="persisted",
    )
    # Live editor is open on a different (real) project.
    live = _write_uproject(tmp_path, "LiveEditorProj")
    monkeypatch.setattr(
        pc, "_live_bridge_context",
        lambda bridge=None: {"project_path": str(live), "project_name": "LiveEditorProj"},
    )
    r = pm.inspect_project()
    assert r.get("ok") is True
    assert r.get("uproject_path") == str(live)
    assert r.get("source_of_truth") == "bridge"


def test_backend_restart_retains_context(tmp_path, iso_context):
    upath = _write_uproject(tmp_path, "RestartProj")
    pc.update_active_context(
        uproject_path=str(upath),
        project_name="RestartProj",
        engine_version="5.8",
        bridge_project_path="/X/Restart.uproject",
        bridge_project_name="RestartProj",
    )
    # Simulate backend restart: reload from the durable file only.
    ctx = pc.load_active_context()
    assert ctx.get("project_name") == "RestartProj"
    assert ctx.get("uproject_path") == str(upath)
    assert ctx.get("engine_version") == "5.8"
    assert ctx.get("validity") == "valid"
    assert ctx.get("bridge_project_path") == "/X/Restart.uproject"
    assert ctx.get("last_verified_at")


def test_editor_restart_recovers_context(tmp_path, iso_context):
    # Editor (bridge) is gone, but the durable context points at a real project.
    upath = _write_uproject(tmp_path, "EditorRestartProj")
    pc.update_active_context(uproject_path=str(upath), project_name="EditorRestartProj")
    # _live_bridge_context already stubbed to {} by the fixture (editor down).
    r = pm.inspect_project()
    assert r.get("ok") is True
    assert r.get("uproject_path") == str(upath)


def test_planner_preserves_explicit_uproject_path():
    from app import api
    task = (
        "Spawn a cube named Box42, save the level, verify it exists and "
        f"capture proof using project C:\\Users\\Shadow\\Desktop\\AvaLive\\AvaLive\\AvaLive.uproject"
    )
    p = api._extract_task_parameters(task)
    assert p.get("uproject_path") == (
        "C:\\Users\\Shadow\\Desktop\\AvaLive\\AvaLive\\AvaLive.uproject"
    )
    # The normalized inspect step must carry that explicit path.
    plan = api.normalize_execution_plan(task, {"goal": task, "steps": [], "success_criteria": []})
    inspect_step = next(s for s in plan["steps"] if s.get("preferred_tool") == "inspect_project")
    assert inspect_step["parameters"].get("uproject_path") == (
        "C:\\Users\\Shadow\\Desktop\\AvaLive\\AvaLive\\AvaLive.uproject"
    )


def test_inspect_project_resolves_and_retries_not_identical(tmp_path, iso_context, monkeypatch):
    """A recovering inspect must re-dispatch WITH a concrete path (never the same
    missing-argument call)."""
    from app import api
    good = _write_uproject(tmp_path, "RecoveryProj")
    candidates = [str(good), "C:\\no\\such1.uproject", "C:\\no\\such2.uproject"]
    dispatch = {
        "ok": False,
        "raw_result": {
            "code": "PROJECT_CONTEXT_MISSING",
            "ok": False,
            "candidates": candidates,
        },
    }
    step = {
        "step_id": "inspect_project:0",
        "phase": "INSPECT",
        "preferred_tool": "inspect_project",
        "parameters": {},
        "status": "running",
    }
    state = {"id": "t", "plan": {"steps": [step]}}
    new_dispatch, attempts = api._recover_project_context_step(state, step, dispatch)
    assert new_dispatch is not None
    assert attempts >= 1
    # The retried call now carries the resolved path -> not the identical no-path call.
    assert step["parameters"].get("uproject_path") == str(good)
    assert new_dispatch.get("ok") is True or new_dispatch.get("transport_success") is True


def test_context_recovery_exhausted_marks_structured_block(tmp_path, iso_context, monkeypatch):
    """None of the candidates resolve -> 3 attempts then a structured BLOCKED verdict."""
    from app import api
    assert iso_context  # keep fixture in scope
    candidates = ["C:\\no\\such1.uproject", "C:\\no\\such2.uproject", "C:\\no\\such3.uproject"]
    dispatch = {
        "ok": False,
        "raw_result": {"code": "PROJECT_CONTEXT_MISSING", "ok": False, "candidates": candidates},
    }
    step = {
        "step_id": "inspect_project:0",
        "phase": "INSPECT",
        "preferred_tool": "inspect_project",
        "parameters": {},
        "status": "running",
    }
    state = {"id": "t", "plan": {"steps": [step]}}
    recovered, attempts = api._recover_project_context_step(state, step, dispatch)
    assert recovered is None
    assert attempts >= 3
    # Exhausted recovery -> deterministic structured BLOCK (not a raw stall).
    state["execution_blocker"] = (
        "PROJECT_CONTEXT_MISSING: no active Unreal project was resolvable after 3 recovery attempts"
    )
    code, blocker = api._terminal_verdict(state)
    assert code == "BLOCKED"
    assert blocker["detail"] == "EXECUTION_BLOCKER"


def test_missing_context_is_detected_before_stall():
    from app import api
    dispatch = {
        "ok": False,
        "raw_result": {"code": "PROJECT_CONTEXT_MISSING", "recoverable": True},
    }
    assert api._is_project_context_missing(dispatch) is True
    assert api._is_project_context_missing({"ok": False, "raw_result": {"error": "x"}}) is False