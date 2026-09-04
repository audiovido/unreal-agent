"""Offline tests for the one-click product shell (core/product_core.py).

These never touch a live editor: the bridge is faked and config/state
files are redirected to a temp dir, so the suite is fully hermetic.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest


@pytest.fixture()
def pc_module(tmp_path, monkeypatch):
    """Import core.product_core with redirected config/state paths."""
    import core.product_core as pc

    monkeypatch.setattr(pc, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(pc, "PRODUCT_CONFIG", tmp_path / "product.json")
    monkeypatch.setattr(pc, "STATE_FILE", tmp_path / "product_state.json")
    return pc


class FakeBridge:
    """Minimal in-memory bridge satisfying the product shell contract."""

    def __init__(self, identity=None):
        self._identity = identity or {}
        self.calls = []

    def ping(self):
        return {"ok": True}

    def get_identity(self):
        return {"result": dict(self._identity), "ok": True}

    def execute_python(self, code):
        self.calls.append(code)
        return {"ok": True, "result": {"ok": True}}

    def capture_unreal_viewport(self):
        return {"ok": True, "path": ""}


def _identity_for(uproject: Path) -> dict:
    p = str(uproject.resolve()).replace("/", "\\")
    return {"project_name": "ASSET_Showcase2", "project_path": p,
            "engine": "5.4", "world": "/Game/ShowcaseMap"}


# ---------------------------------------------------------------------------
# State machine contract (Phase B)
# ---------------------------------------------------------------------------

def test_state_contract_has_all_product_states(pc_module):
    expected = {"IDLE", "CONNECTING_PROJECT", "READY", "UNDERSTANDING_REQUEST",
                "PLANNING", "EXECUTING", "VALIDATING", "SELF_FIXING",
                "COMPLETE", "FAILED", "RECOVERING"}
    assert expected <= set(pc_module.STATES)


def test_state_to_dict_structured(pc_module):
    st = pc_module.ProductState()
    st.state = pc_module.EXECUTING
    st.steps_done = 1
    st.steps_total = 3
    d = st.to_dict()
    for key in ("task_id", "project", "current_stage", "status_text",
                "elapsed_s", "progress", "last_successful_action",
                "active_issue", "retry_count", "final", "proof", "stages"):
        assert key in d, key
    assert d["progress"] == {"completed": 1, "total": 3}


def test_state_never_fabricates_progress_when_unknown(pc_module):
    st = pc_module.ProductState()
    st.state = pc_module.PLANNING
    assert st.to_dict()["progress"] is None


# ---------------------------------------------------------------------------
# Planner: honest capability mapping over real ops (Phase E)
# ---------------------------------------------------------------------------

def _fresh_session(pc_module, tmp_path):
    root = Path(tmp_path) / "proj"
    uproject = root / "ASSET_Showcase2" / "ASSET_Showcase2.uproject"
    uproject.parent.mkdir(parents=True)
    uproject.write_text("{}", encoding="utf-8")
    sess = pc_module.ProductSession()
    fake = FakeBridge(_identity_for(uproject))
    sess._bridge = fake
    return sess, uproject


def test_planner_add_named_cube(pc_module):
    sess, _ = _fresh_session(pc_module, pc_module.CONFIG_DIR)
    plan = sess._plan("Add a cube named MyPropCube to the level")
    assert plan["ok"] is True
    assert plan["capability"] == "add_visible_prop"
    ops = [s["op"] for s in plan["steps"]]
    assert ops == ["spawn_prop", "verify_actor"]
    spawn = plan["steps"][0]
    assert spawn["params"]["name"] == "MyPropCube"
    # the verify step carries the same name => read-back is unambiguous
    assert plan["steps"][1]["params"]["name"] == "MyPropCube"


def test_planner_add_generates_unique_name(pc_module):
    sess, _ = _fresh_session(pc_module, pc_module.CONFIG_DIR)
    plan = sess._plan("please create a prop in the scene")
    assert plan["ok"] is True
    name = plan["steps"][0]["params"]["name"]
    assert name.startswith("UA_Product_")
    assert plan["steps"][1]["params"]["name"] == name


def test_planner_remove_prop_auto_prefix(pc_module):
    sess, _ = _fresh_session(pc_module, pc_module.CONFIG_DIR)
    plan = sess._plan("remove the prop I added")
    assert plan["ok"] is True
    assert plan["capability"] == "remove_actor"
    assert plan["steps"][0]["params"]["name"] == "UA_Product_"


def test_planner_unsupported_fails_actionably(pc_module):
    sess, _ = _fresh_session(pc_module, pc_module.CONFIG_DIR)
    plan = sess._plan("animate a metahuman walk cycle please")
    assert plan["ok"] is False
    assert plan["reason"] and plan["steps"] == []


# ---------------------------------------------------------------------------
# Connect / recovery (Phase C + F)
# ---------------------------------------------------------------------------

def test_connect_reuses_matching_running_editor(pc_module, tmp_path):
    sess, uproject = _fresh_session(pc_module, tmp_path)
    sess._running_editor_pids = lambda: [1234]
    r = sess.connect(str(uproject))
    assert r["ok"] is True
    assert r["state"] == pc_module.READY
    assert r["editor"] == "reused_running_editor"
    assert sess.status()["state"] == pc_module.READY
    # persisted so an app restart stays sane
    data = pc_module._load_json(pc_module.STATE_FILE, {})
    assert data["connection"]["state"] == pc_module.READY


def test_connect_refuses_different_project(pc_module, tmp_path):
    sess, uproject = _fresh_session(pc_module, tmp_path)
    other = tmp_path / "Other" / "Other.uproject"
    other.parent.mkdir()
    other.write_text("{}", encoding="utf-8")
    sess._bridge = FakeBridge(_identity_for(other))
    r = sess.connect(str(uproject))
    assert r["ok"] is False
    assert "Another project" in str(r.get("error"))
    assert r["state"] == pc_module.FAILED


def test_connect_missing_file_is_actionable(pc_module, tmp_path):
    sess = pc_module.ProductSession()
    sess._bridge = FakeBridge({})
    r = sess.connect(str(tmp_path / "nope.uproject"))
    assert r["ok"] is False
    assert "not found" in str(r.get("error"))


def test_run_task_requires_connection(pc_module):
    sess = pc_module.ProductSession()
    # no bridge, no editor process — fails fast, never hangs
    sess._bridge_ok = lambda: False
    sess._bridge_identity = lambda: {}
    r = sess.run_task("Add a cube")
    assert r["ok"] is False
    assert "Not connected" in str(r.get("error"))


def test_run_task_identity_mismatch_guard(pc_module, tmp_path):
    sess, uproject = _fresh_session(pc_module, tmp_path)
    # connect to A, then the editor silently switches to B
    sess.connect(str(uproject))
    other = tmp_path / "B" / "B.uproject"
    other.parent.mkdir()
    other.write_text("{}", encoding="utf-8")
    sess._bridge = FakeBridge(_identity_for(other))
    r = sess.run_task("Add a cube")
    assert r["ok"] is False
    assert "switched projects" in str(r.get("error"))


def test_reconnect_from_saved_state(pc_module, tmp_path):
    sess, uproject = _fresh_session(pc_module, tmp_path)
    sess.connect(str(uproject))
    # simulate an app restart: new session restores READY from disk
    sess2 = pc_module.ProductSession()
    assert sess2.status()["state"] == pc_module.READY
    assert sess2.status()["project"]["uproject_path"] == \
        str(uproject.resolve()).replace("\\", "/")
    # reconnect keeps working
    sess2._bridge = FakeBridge(_identity_for(uproject))
    r = sess2.reconnect()
    assert r["ok"] is True and r["state"] == pc_module.READY


def test_restart_degrades_busy_task_to_failed(pc_module, tmp_path):
    # Simulate an app killed mid-task: persisted state says EXECUTING.
    busy = pc_module.ProductState()
    busy.state = pc_module.EXECUTING
    busy.task_id = "task_deadbeef"
    busy.status_text = "Executing…"
    busy.started_at = 100.0
    pc_module._save_json(pc_module.STATE_FILE, {
        "connection": {"state": pc_module.READY, "project": {},
                       "status_text": "Ready"},
        "task": busy.to_dict(),
    })
    sess = pc_module.ProductSession()
    st = sess.status()
    assert st["state"] == pc_module.FAILED
    assert "interrupted" in st["final"]["reason"]
    assert "restart" in st["status_text"].lower()


def test_known_projects_remembered(pc_module, tmp_path):
    sess, uproject = _fresh_session(pc_module, tmp_path)
    sess.connect(str(uproject))
    known = sess.known_projects()
    want = str(uproject.resolve()).replace("\\", "/").casefold()
    assert any(str(k.get("uproject_path")).replace("\\", "/").casefold()
               == want for k in known)
