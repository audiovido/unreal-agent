"""UNREAL CODER — Phases O + P + Q: failure recovery, checkpoint/resume
stress and loop protection stress.

Failure (O): wrong project, bridge unavailable, editor closed, compile
error, missing asset, vision provider unavailable, Blender unavailable,
missing optional model, repeated identical error -> classified, bounded,
structured outcomes; no infinite loops.

Resume (P): interrupt a multi-step mission mid-run, resume, verify completed
steps are not repeated, evidence/identity preserved, correct final status.

Loop (Q): conditions that previously caused runaway behavior now stop or
change strategy: identical compiler errors, same bridge failure, same
visual score, repeated unsuccessful commands.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.mission import (
    MAX_RECOVERY_PER_CLASS,
    LoopProtector,
    MissionEngine,
    MissionState,
    classify_error,
)
from core.capability_registry import build_capability_registry
from core.universal_intent import expand_requirements, interpret_intent
from core.universal_planner import build_universal_planner
from tools.unreal.project_manager import (
    create_project, discover_projects, inspect_project, open_project,
)


def build_engine(dispatch, tmp_path, capture=None, evaluate=None,
                 repair=None, monkeypatch=None):
    from core import mission as mission_mod
    if monkeypatch:
        monkeypatch.setattr(mission_mod, "CHECKPOINT_DIR", tmp_path / "cp")
    from core.tool_registry import build_registry
    from tools.unreal.unreal_bridge import UnrealBridge
    registry = build_registry(
        discover_projects, inspect_project, open_project, create_project,
        lambda **k: {}, lambda **k: {}, lambda **k: {}, lambda **k: {},
        bridge=UnrealBridge(),
    )
    return MissionEngine(
        tool_registry=registry,
        capabilities=build_capability_registry(registry),
        dispatch=dispatch, capture=capture, evaluate=evaluate,
        repair=repair,
    )


def mission_state(prompt="fix the room", plan_steps=None):
    state = MissionState(mission_id="mission_oqp_test", prompt=prompt)
    state.intent = interpret_intent(prompt).to_dict()
    state.plan = {"steps": plan_steps or [
        {"step_id": "s1", "preferred_tool": "spawn_actor", "phase": "EDIT",
         "parameters": {"actor_name": "A"}},
        {"step_id": "s2", "preferred_tool": "save_level", "phase": "BUILD"},
    ]}
    return state


class TestErrorClassification:
    @pytest.mark.parametrize("text,expected", [
        ("expected_project mismatch: other.uproject", "WRONG_PROJECT"),
        ("bridge connection refused", "BRIDGE"),
        ("blueprint compile failed: bad node", "BLUEPRINT"),
        ("compile error in cl.exe", "CODE_COMPILE"),
        ("asset not found: /Game/Nope", "ASSET_IMPORT"),
        ("import fbx failed to load asset", "ASSET_IMPORT"),
        ("blender executable missing", "EXTERNAL_TOOL"),
        ("ollama model unavailable", "MODEL"),
        ("access denied", "AUTH"),
        ("file not found", "FILESYSTEM"),
        ("editor busy in transaction", "EDITOR_STATE"),
        ("pie begin play crashed", "PIE"),
        ("capture screenshot failed", "VISUAL"),
    ])
    def test_classification(self, text, expected):
        assert classify_error(text) == expected


class TestFailureRecovery:
    def test_bridge_unavailable_bounded_then_fails(self, tmp_path,
                                                   monkeypatch):
        """Bridge down on every call -> bounded retries, classified, FAIL."""
        calls = {"n": 0}

        def dispatch(step):
            calls["n"] += 1
            return {"ok": False, "error": "bridge connection refused"}

        engine = build_engine(dispatch, tmp_path, monkeypatch=monkeypatch)
        state = engine.run(mission_state())
        assert state.verdict in ("FAIL", "BLOCKED")
        assert calls["n"] <= MAX_RECOVERY_PER_CLASS * len(state.plan["steps"]) + 2
        assert any("BRIDGE" in str(e.get("error_class"))
                   for e in state.loop_events)

    def test_wrong_project_is_structured_blocker(self, tmp_path, monkeypatch):
        def dispatch(step):
            return {"ok": False,
                    "error": "expected_project mismatch: Other.uproject"}

        engine = build_engine(dispatch, tmp_path, monkeypatch=monkeypatch)
        state = engine.run(mission_state())
        assert state.verdict in ("FAIL", "BLOCKED")
        classes = {e.get("error_class") for e in state.loop_events}
        assert "WRONG_PROJECT" in classes

    def test_compile_error_classified_and_bounded(self, tmp_path, monkeypatch):
        attempts = {"n": 0}

        def dispatch(step):
            attempts["n"] += 1
            return {"ok": False,
                    "error": "blueprint compile failed: bad node"}

        engine = build_engine(dispatch, tmp_path, monkeypatch=monkeypatch)
        state = engine.run(mission_state())
        assert attempts["n"] <= 8
        assert state.recovery_attempts.get("BLUEPRINT", 0) >= 1

    def test_missing_asset_routes_intake_recovery(self, tmp_path,
                                                  monkeypatch):
        seen_actions = []

        real_policy = dict(__import__(
            "core.mission", fromlist=["RECOVERY_POLICY"]).RECOVERY_POLICY)

        def dispatch(step):
            return {"ok": False, "error": "asset not found: /Game/X"}

        engine = build_engine(dispatch, tmp_path, monkeypatch=monkeypatch)
        state = engine.run(mission_state())
        events = [e for e in state.loop_events
                  if e.get("error_class") == "ASSET_IMPORT"]
        assert events
        assert any(e.get("recovery") in ("reintake", "blender_route", "stop")
                   for e in events)

    def test_transient_failure_recovers(self, tmp_path, monkeypatch):
        """First call fails, retry succeeds -> step completes."""
        calls = {"n": 0}

        def dispatch(step):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"ok": False, "error": "bridge connection refused"}
            return {"ok": True}

        engine = build_engine(dispatch, tmp_path, monkeypatch=monkeypatch)
        state = engine.run(mission_state())
        assert state.verdict == "PASS"
        assert calls["n"] == 3  # 1 fail + retry, then next step

    def test_repeated_identical_error_changes_strategy(self, tmp_path,
                                                       monkeypatch):
        """Same error every time -> engine stops, records events, no loop."""
        calls = {"n": 0}

        def dispatch(step):
            calls["n"] += 1
            return {"ok": False, "error": "editor busy in transaction"}

        engine = build_engine(dispatch, tmp_path, monkeypatch=monkeypatch)
        state = engine.run(mission_state())
        assert state.verdict in ("FAIL", "BLOCKED")
        assert calls["n"] < 20  # bounded

    def test_vision_unavailable_does_not_crash_mission(self, tmp_path,
                                                       monkeypatch):
        """Visual gate with dead capture -> structured result, no crash."""
        def dispatch(step):
            return {"ok": True}

        def capture():
            return {"ok": False, "error": "capture tool unavailable"}

        engine = build_engine(
            dispatch, tmp_path, capture=capture,
            evaluate=lambda c: {"score": 0.0, "defects": ["CAPTURE_FAILED"]},
            repair=lambda d: "noop", monkeypatch=monkeypatch)
        state = mission_state(plan_steps=[
            {"step_id": "s1", "preferred_tool": "spawn_actor",
             "phase": "EDIT"},
        ])
        state.plan["visual_gate"] = {"enabled": True, "score_floor": 7.0}
        result = engine.run(state)
        assert result.verdict in ("PARTIAL", "FAIL", "BLOCKED")
        assert any("CAPTURE" in i or "VISUAL" in i
                   for i in result.remaining_issues)


class TestCheckpointResume:
    def test_resume_skips_completed_steps(self, tmp_path, monkeypatch):
        from core import mission as mission_mod
        monkeypatch.setattr(mission_mod, "CHECKPOINT_DIR", tmp_path / "cp")
        # First run: step budget interrupts after s1 completes.
        engine = build_engine(lambda s: {"ok": True}, tmp_path,
                              monkeypatch=monkeypatch)
        state = mission_state()
        state.save()
        state1 = engine.run(state, max_steps=1)
        assert state1.completed_step_ids == ["s1"]
        assert state1.verdict is None

        # Resume: tracked dispatch proves s1 is NOT re-executed.
        executed = []

        def tracked(step):
            executed.append(step["step_id"])
            return {"ok": True}

        engine2 = build_engine(tracked, tmp_path, monkeypatch=monkeypatch)
        state2 = engine2.run(MissionState.load(state.mission_id),
                             max_steps=10)
        assert executed == ["s2"], f"re-executed completed steps: {executed}"
        assert state2.completed_step_ids == ["s1", "s2"]

    def test_resume_preserves_mission_identity(self, tmp_path, monkeypatch):
        from core import mission as mission_mod
        monkeypatch.setattr(mission_mod, "CHECKPOINT_DIR", tmp_path / "cp")
        state = mission_state()
        state.intent = {"domains": ["ui"], "quality": "high"}
        state.evidence.append({"path": "/tmp/evidence.png", "ok": True})
        state.completed_step_ids = ["s1"]
        state.save()
        loaded = MissionState.load(state.mission_id)
        assert loaded.mission_id == state.mission_id
        assert loaded.intent["domains"] == ["ui"]
        assert loaded.evidence[0]["path"] == "/tmp/evidence.png"
        assert loaded.completed_step_ids == ["s1"]

    def test_interrupted_mission_resumes_to_completion(self, tmp_path,
                                                       monkeypatch):
        from core import mission as mission_mod
        monkeypatch.setattr(mission_mod, "CHECKPOINT_DIR", tmp_path / "cp")
        # Distinct parameters -> distinct signatures (loop protection is
        # about repeated identical work, not legitimate sequences).
        engine = build_engine(lambda s: {"ok": True}, tmp_path,
                              monkeypatch=monkeypatch)
        state = mission_state()
        state.plan["steps"] = [
            {"step_id": f"s{i}", "preferred_tool": "move_actor",
             "phase": "EDIT", "parameters": {"location": [i, 0, 0]}}
            for i in range(5)]
        state1 = engine.run(state, max_steps=2)
        assert state1.status == "executing"  # checkpoint saved, not terminal
        assert state1.verdict is None
        # Resume completes the rest from the persisted checkpoint.
        state2 = engine.run(MissionState.load(state.mission_id), max_steps=10)
        assert state2.verdict == "PASS"
        assert len(state2.completed_step_ids) == 5
        assert state2.status == "complete"
        # Evidence of interruption preserved in the resumed state.
        assert state2.mission_id == state.mission_id


class TestLoopProtection:
    def test_identical_step_signature_stops(self):
        protector = LoopProtector()
        assert protector.observe("spawn:{}") == "ok"
        assert protector.observe("spawn:{}") == "repeat"
        assert protector.observe("spawn:{}") == "stop"

    def test_distinct_steps_never_trigger(self):
        protector = LoopProtector()
        for i in range(10):
            assert protector.observe(f"step_{i}:{{}}") == "ok"

    def test_visual_stagnation_stops_repair(self, tmp_path, monkeypatch):
        """Same visual score twice -> repair loop stops (STAGNANT)."""
        scores = iter([5.0, 5.0, 5.0])
        repairs = {"n": 0}

        def dispatch(step):
            return {"ok": True}

        engine = build_engine(
            dispatch, tmp_path, capture=lambda: {"ok": True,
                                                 "path": "x.png"},
            evaluate=lambda c: {"score": next(scores), "defects": ["DARK"]},
            repair=lambda d: repairs.__setitem__("n", repairs["n"] + 1)
            or "repaired", monkeypatch=monkeypatch)
        state = mission_state(plan_steps=[
            {"step_id": "s1", "preferred_tool": "spawn_actor",
             "phase": "EDIT"}])
        state.plan["visual_gate"] = {"enabled": True, "score_floor": 7.0}
        result = engine.run(state)
        assert repairs["n"] <= 1  # one repair, then stagnation stop
        assert result.verdict == "PARTIAL"

    def test_no_progress_budget_stops_mission(self, tmp_path, monkeypatch):
        """Consecutive failures with no recovery progress -> FAIL, stop.
        Distinct parameters so this exercises the no-progress path (not the
        identical-signature path, which has its own test)."""
        def dispatch(step):
            return {"ok": False, "error": "connection refused"}

        engine = build_engine(dispatch, tmp_path, monkeypatch=monkeypatch)
        state = mission_state(plan_steps=[
            {"step_id": f"s{i}", "preferred_tool": "move_actor",
             "phase": "EDIT", "parameters": {"location": [i, 0, 0]}}
            for i in range(6)])
        result = engine.run(state)
        assert result.verdict in ("FAIL", "BLOCKED")
        assert result.status in ("failed", "blocked")
        # It stopped early: not all six steps were dispatched.
        dispatched = {e.get("step_id") for e in result.loop_events} | \
            set(result.step_results)
        assert len(dispatched) < 6

    def test_step_budget_saves_checkpoint(self, tmp_path, monkeypatch):
        """Step budget reached -> checkpoint saved, resumable."""
        engine = build_engine(lambda s: {"ok": True}, tmp_path,
                              monkeypatch=monkeypatch)
        state = mission_state(plan_steps=[
            {"step_id": f"s{i}", "preferred_tool": "move_actor",
             "phase": "EDIT", "parameters": {"location": [i, 0, 0]}}
            for i in range(100)])
        result = engine.run(state, max_steps=10)
        assert "step budget" in " ".join(result.remaining_issues)
        assert result.verdict is None
        assert MissionState.load(result.mission_id) is not None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
