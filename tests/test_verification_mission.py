"""Hermetic tests for the V1 defect closure.

Covers the three verified black-box defects WITHOUT a live backend, bridge
or Unreal session:

  D1 (MAJOR) explicit verification requirements are skipped
      -> verification intent parsing + one real read-only step per check
  D2 (MAJOR) false PASS
      -> the verdict gate makes PASS impossible while any explicit
         requirement is NOT_PLANNED / NOT_EXECUTED / NOT_EVIDENCED
         (truthful UNVERIFIED_REQUIREMENTS / REQUESTED_TOOL_MISSING /
         BLOCKED)
  D3 (MINOR) Mission Control evidence shows [object Object]
      -> evidence payloads stay structured (kind/measured/expected/...) so
         the frontend formatter can render them human-readably

No ports are bound; no processes are spawned; nothing is mutated.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.capability_registry import build_capability_registry  # noqa: E402
from core.mission import MissionEngine, MissionState  # noqa: E402
from core.mission_policy import (  # noqa: E402
    classify_tool,
    plan_violations,
)
from core.universal_intent import (  # noqa: E402
    expand_requirements,
    interpret_intent,
    parse_explicit_checks,
)
from core.universal_planner import UniversalPlanner  # noqa: E402
from tools.unreal.scene_verification import SceneVerification  # noqa: E402

LIVE_VERIFY_PROMPT = (
    "Run the exact strict read-only AividoHQ verification: "
    "map AividoHQ, bridge healthy, exactly 8 human agents, "
    "exactly 23 W3I props, exactly 41 movable lights, "
    "missing skeletal meshes, missing prop mesh/material references, "
    "fresh real viewport proof"
)

REGISTRY_TOOLS = ("inspect_project", "unreal_ping", "verify_scene",
                  "capture_unreal_viewport", "list_level_actors")


@pytest.fixture(autouse=True)
def _isolated_checkpoints(tmp_path, monkeypatch):
    """Mission validate() persists checkpoints; keep tests hermetic."""
    import core.mission as mission_mod
    monkeypatch.setattr(mission_mod, "CHECKPOINT_DIR",
                        tmp_path / "checkpoints")


def fake_registry(include_verify_scene: bool = True) -> dict:
    tools = {name: None for name in REGISTRY_TOOLS}
    if not include_verify_scene:
        tools.pop("verify_scene")
    return tools


# ---------------------------------------------------------------------------
# D1 — intent parsing: explicit verification requirements become real work
# ---------------------------------------------------------------------------

def test_verification_intent_is_read_only_execute():
    intent = interpret_intent(LIVE_VERIFY_PROMPT)
    assert intent.verification is True
    assert intent.mode == "execute"
    assert intent.read_only is True
    assert intent.needs_visual_validation is False


def test_verification_intent_parses_all_explicit_checks():
    checks = {c["id"]: c for c in parse_explicit_checks(LIVE_VERIFY_PROMPT)}
    assert set(checks) == {
        "active_map", "bridge_ready", "human_count", "prop_count",
        "movable_lights", "missing_skeletal_meshes",
        "missing_prop_references", "viewport_proof",
    }
    assert checks["active_map"]["kind"] == "map"
    assert checks["active_map"]["expected"] == "AividoHQ"
    assert checks["human_count"] == {
        "id": "human_count", "kind": "count", "expected": 8,
        "target": "AVIDO_Human",
        "desc": "exactly 8 human agents", "label": "human agent",
    }
    assert checks["prop_count"]["expected"] == 23
    assert checks["prop_count"]["target"] == "W3I_"
    assert checks["movable_lights"]["expected"] == 41
    assert checks["missing_skeletal_meshes"]["expected"] == 0
    assert checks["missing_prop_references"]["expected"] == 0
    assert checks["viewport_proof"]["kind"] == "proof"


def test_verification_requirements_one_entry_per_check():
    intent = interpret_intent(LIVE_VERIFY_PROMPT)
    spec = expand_requirements(intent)
    ver = [r for r in spec.requirements
           if r.get("kind") == "verification" and r.get("explicit")]
    assert len(ver) == 8
    ids = {r["check"]["id"] for r in ver}
    assert ids == {
        "active_map", "bridge_ready", "human_count", "prop_count",
        "movable_lights", "missing_skeletal_meshes",
        "missing_prop_references", "viewport_proof",
    }


def test_unparseable_verification_stays_explicit():
    # An explicit count with no deterministic target must remain a truthful
    # explicit requirement (reported UNVERIFIED) — never silently dropped.
    intent = interpret_intent(
        "Run read-only verification: exactly 8 gnomes in the scene")
    assert intent.verification is True
    checks = parse_explicit_checks(intent.prompt)
    gnomes = [c for c in checks if c.get("kind") == "count"
              and c.get("target") is None]
    assert gnomes and gnomes[0]["expected"] == 8
    spec = expand_requirements(intent)
    assert any(r.get("kind") == "verification" and r.get("explicit")
               for r in spec.requirements)


# ---------------------------------------------------------------------------
# D1 — planner: one real READ_ONLY step per explicit check
# ---------------------------------------------------------------------------

def _plan_for(prompt: str, registry: dict):
    intent = interpret_intent(prompt)
    requirements = expand_requirements(intent)
    planner = UniversalPlanner(build_capability_registry(registry))
    return intent, requirements, planner.build_plan(intent, requirements, {})


def test_verification_plan_one_step_per_check_all_read_only():
    _, _, plan = _plan_for(LIVE_VERIFY_PROMPT, fake_registry())
    steps = plan.normalized_steps()
    covers = {s["covers"] for s in steps if s.get("covers")}
    assert covers == {
        "active_map", "bridge_ready", "human_count", "prop_count",
        "movable_lights", "missing_skeletal_meshes",
        "missing_prop_references", "viewport_proof",
    }
    tools = {s["preferred_tool"] for s in steps}
    assert tools <= {"inspect_project", "unreal_ping", "verify_scene",
                     "capture_unreal_viewport"}
    # Read-only policy: zero violations, so the plan gate can never reject
    # a verification mission for trying to mutate.
    assert plan_violations(True, steps) == []
    verify = [s for s in steps if s.get("covers") == "human_count"]
    assert verify[0]["preferred_tool"] == "verify_scene"
    assert verify[0]["parameters"]["check"] == "count"
    assert verify[0]["parameters"]["expected"] == 8
    assert verify[0]["parameters"]["target"] == "AVIDO_Human"
    proof = [s for s in steps if s.get("covers") == "viewport_proof"]
    assert proof[0]["preferred_tool"] == "capture_unreal_viewport"
    assert proof[0]["phase"] == "EVIDENCE"


def test_verification_plan_unknown_count_is_not_false_planned():
    _, _, plan = _plan_for(
        "Run read-only verification: exactly 8 gnomes in the scene",
        fake_registry())
    steps = plan.to_dict()["steps"]
    # No step may be invented for an under-specified count: leaving it
    # unplanned is what makes the verdict gate report UNVERIFIED.
    assert not any("gnome" in str(s.get("stop_condition") or "").lower()
                   for s in steps)
    assert any("unverified" in w.lower() or "cannot be planned" in w.lower()
               for w in plan.warnings)


def test_verification_plan_tool_missing_records_skipped():
    _, _, plan = _plan_for(LIVE_VERIFY_PROMPT,
                           fake_registry(include_verify_scene=False))
    skipped = plan.skipped_capabilities
    assert "scene_verification" in skipped
    assert "verify_scene" in skipped["scene_verification"]


# ---------------------------------------------------------------------------
# D2 — the false-PASS gate
# ---------------------------------------------------------------------------

class FakeBridge:
    """Canned read-only bridge: returns the recorded payload per script."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def ping(self):
        return {"ok": True, "result": {"ok": True}}

    def execute_python(self, code, **kwargs):
        self.calls.append(code)
        for marker, payload in self.responses:
            if marker in code:
                return {"ok": True, "result": payload}
        return {"ok": True, "result": {"ok": False,
                                       "error": "no canned response"}}


def _state_with_plan(prompt: str, registry: dict) -> MissionState:
    intent, requirements, plan = _plan_for(prompt, registry)
    state = MissionState(mission_id="mission_verif_test", prompt=prompt)
    state.intent = intent.to_dict()
    state.requirements = requirements.to_dict()
    state.plan = plan.to_dict()
    state.read_only = True
    return state


def _complete_all_steps(state: MissionState) -> None:
    for step in state.plan["steps"]:
        sid = step["step_id"]
        state.completed_step_ids.append(sid)
        payload = {"ok": True, "measured": 8, "expected": 8,
                   "detail": "canned pass"}
        if step.get("covers") == "active_map":
            payload = {"ok": True, "measured": "AividoHQ",
                       "expected": "AividoHQ",
                       "path": "/Game/Maps/AividoHQ.AividoHQ",
                       "detail": "map ok"}
        elif step.get("covers") == "bridge_ready":
            payload = {"ok": True, "measured": "healthy",
                       "expected": "healthy", "detail": "bridge ok"}
        elif step.get("covers") == "viewport_proof":
            payload = {"ok": True, "path": "C:/proof.png", "size": 1234}
        elif step.get("covers") == "movable_lights":
            payload = {"ok": True, "measured": 41, "expected": 41,
                       "detail": "41 movable"}
        elif step.get("covers") == "missing_skeletal_meshes":
            payload = {"ok": True, "measured": 0, "expected": 0,
                       "detail": "0 missing"}
        elif step.get("covers") == "missing_prop_references":
            payload = {"ok": True, "measured": 0, "expected": 0,
                       "detail": "0 missing"}
        state.step_results[sid] = {"ok": True, "result": payload}


def _engine(registry: dict) -> MissionEngine:
    return MissionEngine(
        tool_registry=registry,
        capabilities=build_capability_registry(registry),
        dispatch=lambda step: {"ok": True},
        capture=None,
    )


def test_verdict_all_verified_passes():
    state = _state_with_plan(LIVE_VERIFY_PROMPT, fake_registry())
    _complete_all_steps(state)
    engine = _engine(fake_registry())
    engine.validate(state)
    assert state.verdict == "PASS", state.why
    # PASS must carry per-requirement evidence (never an empty evidence list).
    ev = state.evidence
    assert len(ev) >= 8
    kinds = {e.get("kind") for e in ev}
    assert "verification" in kinds and "viewport_capture" in kinds
    measured = {e.get("check"): e.get("measured") for e in ev
                if e.get("kind") == "verification"}
    assert measured["human_count"] == 8
    assert measured["movable_lights"] == 41
    # Evidence entries must be structured dicts (D3): the frontend formatter
    # needs fields, and String(obj) must never be the fallback for them.
    assert all(isinstance(e, dict) for e in ev)


def test_verdict_unplanned_requirement_fails_truthfully():
    state = _state_with_plan(LIVE_VERIFY_PROMPT, fake_registry())
    # Simulate the planner dropping one explicit check (e.g. unsupported):
    # remove the human_count covering step entirely.
    state.plan["steps"] = [
        s for s in state.plan["steps"] if s.get("covers") != "human_count"]
    _complete_all_steps(state)
    engine = _engine(fake_registry())
    engine.validate(state)
    assert state.verdict == "FAIL", state.why
    assert "UNVERIFIED_REQUIREMENTS" in state.why
    assert "NOT_PLANNED" in state.why
    assert "human agents" in state.why


def test_verdict_unexecuted_requirement_fails_truthfully():
    state = _state_with_plan(LIVE_VERIFY_PROMPT, fake_registry())
    _complete_all_steps(state)
    # The human_count step ran and is evidenced, but prop_count never ran.
    dropped = [s["step_id"] for s in state.plan["steps"]
               if s.get("covers") == "prop_count"]
    for sid in dropped:
        if sid in state.completed_step_ids:
            state.completed_step_ids.remove(sid)
    engine = _engine(fake_registry())
    engine.validate(state)
    assert state.verdict == "FAIL", state.why
    assert "UNVERIFIED_REQUIREMENTS" in state.why
    assert "NOT_EXECUTED" in state.why


def test_verdict_un_evidenced_requirement_fails_truthfully():
    state = _state_with_plan(LIVE_VERIFY_PROMPT, fake_registry())
    _complete_all_steps(state)
    engine = _engine(fake_registry())
    # No verification evidence is emitted at all -> every check un-evidenced.
    engine._emit_verification_evidence = lambda s: None
    engine.validate(state)
    assert state.verdict == "FAIL", state.why
    assert "UNVERIFIED_REQUIREMENTS" in state.why
    assert "NOT_EVIDENCED" in state.why


def test_verdict_tool_missing_is_blocked_requested_tool_missing():
    registry = fake_registry(include_verify_scene=False)
    state = _state_with_plan(LIVE_VERIFY_PROMPT, registry)
    _complete_all_steps(state)
    engine = _engine(registry)
    engine.validate(state)
    assert state.verdict == "BLOCKED", state.why
    assert "REQUESTED_TOOL_MISSING" in state.why
    assert "verify_scene" in state.why


def test_verdict_zero_steps_cannot_pass():
    # A verification mission whose plan executed nothing must never PASS.
    state = _state_with_plan(LIVE_VERIFY_PROMPT, fake_registry())
    engine = _engine(fake_registry())
    engine.validate(state)
    assert state.verdict != "PASS"


# ---------------------------------------------------------------------------
# verify_scene tool — real, read-only, measured
# ---------------------------------------------------------------------------

def _verifier(responses):
    return SceneVerification(FakeBridge(responses))


def test_verify_scene_count_prefix_measures_exact_count():
    sv = _verifier([("label.startswith(prefix)", {
        "ok": True, "measured": 8, "actors": [f"AVIDO_Human_{i}"
                                              for i in range(8)],
        "target": "AVIDO_Human"})])
    res = sv.verify(check="count_prefix", expected=8, target="AVIDO_Human")
    assert res["ok"] is True
    assert res["measured"] == 8
    assert res["expected"] == 8


def test_verify_scene_count_prefix_fails_truthfully_on_mismatch():
    sv = _verifier([("label.startswith(prefix)", {
        "ok": True, "measured": 7, "actors": [], "target": "AVIDO_Human"})])
    res = sv.verify(check="count_prefix", expected=8, target="AVIDO_Human")
    assert res["ok"] is False
    assert res["measured"] == 7
    assert res["expected"] == 8


def test_verify_scene_missing_skeletal_reports_measured_missing():
    sv = _verifier([("SkeletalMeshComponent", {
        "ok": True, "measured": 1, "missing": ["AVIDO_Human_3 (null skeletal mesh)"],
        "checked": ["AVIDO_Human_1", "AVIDO_Human_2", "AVIDO_Human_3"],
        "target": "AVIDO_Human"})])
    res = sv.verify(check="missing_skeletal_meshes", expected=0,
                    target="AVIDO_Human")
    assert res["ok"] is False
    assert res["measured"] == 1
    assert res["missing"] == ["AVIDO_Human_3 (null skeletal mesh)"]


def test_verify_scene_map_accepts_name_or_path():
    sv = _verifier([("get_editor_world", {
        "ok": True, "measured": "AividoHQ",
        "path": "/Game/Maps/AividoHQ.AividoHQ"})])
    res = sv.verify(check="map", expected="AividoHQ")
    assert res["ok"] is True
    res2 = sv.verify(check="map", expected="/Game/Maps/AividoHQ")
    assert res2["ok"] is True


def test_verify_scene_is_classified_read_only():
    assert classify_tool("verify_scene") == "READ_ONLY"


def test_verify_scene_never_mutates_payload_shape():
    sv = _verifier([("label.startswith(prefix)", {
        "ok": True, "measured": 8, "actors": [], "target": "AVIDO_Human"})])
    res = sv.verify(check="count_prefix", expected=8, target="AVIDO_Human")
    # Flat, JSON-serializable payload: the frontend renders fields directly.
    json.dumps(res)
    assert set(res) >= {"ok", "check", "measured", "expected"}


def test_verify_scene_unsupported_check_is_truthful():
    sv = _verifier([])
    res = sv.verify(check="teleport_cubes", expected=1)
    assert res["ok"] is False
    assert "unsupported verification check" in res["error"]