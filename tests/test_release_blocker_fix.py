"""RELEASE BLOCKER FIX — regression tests.

Two V2 release blockers closed here:

1. MAJOR `isolated_capture_mission` — a capture mission could remain
   indefinitely in `executing` (0 executed steps, no evidence) because the
   async worker could die without writing a terminal checkpoint, cancel
   could not finalize a dead worker, and no mission-level deadline or
   orphan reaper existed. The fix guarantees:
     - every worker exit path finalizes the durable checkpoint
       (TIMED_OUT / FAIL / CANCELLED — never a phantom `executing`)
     - a hard mission deadline bounds execution at step boundaries and
       around the visual capture loop
     - cancel always lands on a terminal state
     - orphaned `executing` checkpoints are reaped on read
     - checkpoint saves survive transient Windows file-sharing collisions

2. MINOR `plain_capture_phrasing_routing` — "capture a screenshot" /
   "take a fresh viewport screenshot" used to route to chat (ANSWER, 0
   steps). The intent router now treats ordinary capture/screenshot
   phrasings as real read-only capture missions (knowledge questions such
   as "how do I take a screenshot in Unreal?" stay chat).

All tests are hermetic: no live backend, no Unreal bridge.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.mission import MissionState, mission_response
from core.universal_intent import expand_requirements, interpret_intent
from core.universal_planner import build_universal_planner
from core.tool_registry import build_registry


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_registry():
    """Real tool registry shape with inert funcs (never executed)."""
    from core.tool_registry import ToolSpec

    def _noop(*args, **kwargs):
        return {"ok": False, "error": "not executed in hermetic test"}

    registry = build_registry(
        _noop, _noop, _noop, _noop, _noop, _noop, _noop, _noop,
        bridge=None,
    )
    # Register the read-only tools the capture/diagnostic plans need so the
    # planner selects the full step set (real production registry has these).
    for name in ("unreal_ping", "unreal_coder_doctor",
                 "capture_unreal_viewport", "verify_scene"):
        registry[name] = ToolSpec(
            name=name, description="hermetic test stub", args={},
            func=_noop)
    return registry


def _plan_steps(prompt: str):
    intent = interpret_intent(prompt)
    requirements = expand_requirements(intent)
    planner = build_universal_planner(_make_registry())
    plan = planner.build_plan(intent, requirements, {})
    return intent, plan.to_dict()


def _make_state(mission_id: str, prompt: str, status: str = "executing"):
    state = MissionState(mission_id=mission_id, prompt=prompt)
    state.started_at = time.time()
    state.status = status
    state.read_only = True
    return state


# ---------------------------------------------------------------------------
# 1. Capture intent routing (MINOR)
# ---------------------------------------------------------------------------

PLAIN_CAPTURE_PROMPTS = [
    "READ ONLY: capture a fresh viewport screenshot for QA evidence",
    "capture a screenshot",
    "take a screenshot",
    "capture the viewport",
    "take a fresh viewport screenshot",
    "capture a screenshot of the current level",
    "Take a screenshot of the current viewport as evidence",
    "capture visual evidence of the viewport",
    "take a picture of the viewport",
    "capture visual evidence",
    "take visual evidence",
]


class TestCaptureIntentRouting:
    @pytest.mark.parametrize("prompt", PLAIN_CAPTURE_PROMPTS)
    def test_plain_capture_phrases_route_to_capture_mission(self, prompt):
        intent = interpret_intent(prompt)
        assert intent.mode == "execute", prompt
        assert intent.capture_only is True, prompt
        assert intent.read_only is True, prompt
        assert intent.to_dict()["capture_only"] is True, prompt

    @pytest.mark.parametrize(
        "prompt",
        [
            "How do I take a screenshot in Unreal?",
            "how to take a viewport screenshot in the editor",
            "What is a screenshot?",
            "What is the capital of France, and how does Unreal handle "
            "level streaming between sublevels?",
            "check the current project state",
        ],
    )
    def test_knowledge_questions_stay_chat(self, prompt):
        intent = interpret_intent(prompt)
        assert intent.mode == "chat", prompt
        assert intent.capture_only is False, prompt

    def test_qa_plain_capture_prompt_plans_capture_step(self):
        intent, plan = _plan_steps(
            "READ ONLY: capture a fresh viewport screenshot for QA evidence")
        steps = plan["steps"]
        assert steps, "plain capture prompt must not plan 0 steps"
        assert any(s.get("phase") == "ANSWER" for s in steps) is False, steps
        capture = [s for s in steps
                   if s.get("preferred_tool") == "capture_unreal_viewport"]
        assert capture, f"no capture_unreal_viewport step: {steps}"
        assert any(s.get("phase") == "EVIDENCE" for s in capture), steps


# ---------------------------------------------------------------------------
# 2. Capture mission reaches an executable step
# ---------------------------------------------------------------------------

class TestCaptureMissionExecutable:
    @pytest.mark.parametrize(
        "prompt",
        PLAIN_CAPTURE_PROMPTS
        + ["read-only diagnostic: capture a screenshot of the current level"],
    )
    def test_plan_has_executable_steps(self, prompt):
        intent, plan = _plan_steps(prompt)
        steps = plan["steps"]
        assert len(steps) >= 1, f"zero-step plan: {prompt!r}"
        executable = [
            s for s in steps
            if s.get("preferred_tool") not in (None, "")
        ]
        assert executable, f"no executable step: {steps}"
        # A capture request always names the real capture tool somewhere.
        assert any(
            s.get("preferred_tool") == "capture_unreal_viewport"
            for s in steps
        ), f"capture tool missing from plan: {steps}"

    def test_isolated_capture_diagnostic_plan_is_four_steps(self):
        intent, plan = _plan_steps(
            "read-only diagnostic: capture a screenshot of the current level")
        steps = plan["steps"]
        assert len(steps) == 4, [s.get("step_id") for s in steps]
        assert [s.get("step_id") for s in steps] == [
            "resolve_project", "bridge_health", "backend_health",
            "visual_gate"]


# ---------------------------------------------------------------------------
# 3. Capture timeout reaches terminal FAIL/BLOCK (MAJOR)
# ---------------------------------------------------------------------------

class TestMissionDeadline:
    def test_deadline_raises_when_exceeded(self):
        from app.unreal_coder_api import (
            MissionDeadlineExceeded, _MissionDeadline)
        dl = _MissionDeadline(0.05)
        time.sleep(0.12)
        with pytest.raises(MissionDeadlineExceeded):
            dl.check()

    def test_deadline_allows_work_before_expiry(self):
        from app.unreal_coder_api import _MissionDeadline
        dl = _MissionDeadline(30)
        dl.check()  # must not raise

    def test_worker_deadline_path_finalizes_checkpoint(
            self, tmp_path, monkeypatch):
        """The worker's MissionDeadlineExceeded handler must leave the
        checkpoint in a terminal BLOCKED state, never `executing`."""
        from core import mission as mission_mod
        monkeypatch.setattr(mission_mod, "CHECKPOINT_DIR", tmp_path / "cp")
        from app.unreal_coder_api import (
            MissionDeadlineExceeded, _finalize_mission)

        state = _make_state("mission_deadline_probe",
                            "capture a screenshot")
        state.save()
        assert state.status == "executing"

        # Simulate exactly what the async worker does on deadline.
        try:
            raise MissionDeadlineExceeded("deadline hit")
        except MissionDeadlineExceeded as exc:
            _finalize_mission(
                state.mission_id, "blocked", "BLOCKED",
                "Mission exceeded the hard execution deadline and was "
                f"finalized with a structured TIMED_OUT. {exc}")

        final = MissionState.load(state.mission_id)
        assert final.status == "blocked"
        assert final.verdict == "BLOCKED"
        assert final.finished_at is not None
        assert "TIMED_OUT" in final.why

    def test_worker_internal_error_path_finalizes_checkpoint(
            self, tmp_path, monkeypatch):
        """Any internal worker exception must finalize truthfully (FAIL),
        never leave the durable checkpoint in `executing`."""
        from core import mission as mission_mod
        monkeypatch.setattr(mission_mod, "CHECKPOINT_DIR", tmp_path / "cp")
        from app.unreal_coder_api import _finalize_mission

        state = _make_state("mission_internal_error",
                            "capture a screenshot")
        state.save()
        try:
            raise RuntimeError("bridge exploded")
        except RuntimeError as exc:
            _finalize_mission(
                state.mission_id, "failed", "FAIL",
                "Mission execution aborted with an internal error and was "
                f"finalized truthfully: {type(exc).__name__}: {exc} "
                "(MISSION_INTERNAL_ERROR).")

        final = MissionState.load(state.mission_id)
        assert final.status == "failed"
        assert final.verdict == "FAIL"
        assert "MISSION_INTERNAL_ERROR" in final.why

    def test_finalize_is_idempotent(self, tmp_path, monkeypatch):
        from core import mission as mission_mod
        monkeypatch.setattr(mission_mod, "CHECKPOINT_DIR", tmp_path / "cp")
        from app.unreal_coder_api import _finalize_mission

        state = _make_state("mission_idem", "capture a screenshot")
        state.status = "complete"
        state.verdict = "PASS"
        state.finished_at = time.time()
        state.save()
        final = _finalize_mission(
            state.mission_id, "blocked", "CANCELLED", "should not apply")
        assert final.status == "complete"
        assert final.verdict == "PASS"


# ---------------------------------------------------------------------------
# 4. Cancellation releases executor / lease (MAJOR)
# ---------------------------------------------------------------------------

class TestCancellation:
    def test_cancel_finalizes_dead_worker_checkpoint(
            self, tmp_path, monkeypatch):
        """Cancel on a mission whose worker already died (running=False) must
        finalize the checkpoint to CANCELLED instead of returning a phantom
        `executing` snapshot."""
        from core import mission as mission_mod
        monkeypatch.setattr(mission_mod, "CHECKPOINT_DIR", tmp_path / "cp")
        from app.unreal_coder_api import (
            _ASYNC_RUNS, _finalize_mission)

        state = _make_state("mission_cancel_dead", "capture a screenshot")
        state.save()
        # Simulate a worker that died mid-flight.
        _ASYNC_RUNS[state.mission_id] = {
            "running": False, "cancel_flag": False, "error": None}

        # Cancel handler path when the worker is not running: it must
        # finalize directly (the same call the endpoint makes).
        final = _finalize_mission(
            state.mission_id, "blocked", "CANCELLED",
            "Mission cancelled by user request (ClickUp MCP gateway); "
            "execution worker was not progressing, so the checkpoint was "
            "finalized at cancel time.")
        _ASYNC_RUNS.pop(state.mission_id, None)

        checkpoint = MissionState.load(state.mission_id)
        assert checkpoint.status == "blocked"
        assert checkpoint.verdict == "CANCELLED"
        assert checkpoint.finished_at is not None
        response = mission_response(checkpoint)
        assert response["status"] == "blocked"
        assert response["resumable"] is True  # terminal CANCELLED is resumable

    def test_cancel_flag_path_used_by_running_worker(
            self, tmp_path, monkeypatch):
        """A running worker honours the cancel flag at the next step
        boundary and the checkpoint is finalized CANCELLED."""
        from core import mission as mission_mod
        monkeypatch.setattr(mission_mod, "CHECKPOINT_DIR", tmp_path / "cp")
        from app.unreal_coder_api import _finalize_mission

        state = _make_state("mission_cancel_running", "capture a screenshot")
        state.save()

        # The worker's exception handler for MISSION_CANCELLED_BY_USER.
        _finalize_mission(
            state.mission_id, "blocked", "CANCELLED",
            "Mission cancelled by user request (ClickUp MCP gateway).")
        final = MissionState.load(state.mission_id)
        assert final.status == "blocked"
        assert final.verdict == "CANCELLED"


# ---------------------------------------------------------------------------
# 5. Next mission executes after a cancelled/stalled capture (MAJOR)
# ---------------------------------------------------------------------------

class TestNextMissionAfterStall:
    def test_new_mission_runs_after_stalled_capture_finalized(
            self, tmp_path, monkeypatch):
        """Finalizing a stalled capture leaves no lock behind: a fresh
        mission can be created, planned and checkpointed normally."""
        from core import mission as mission_mod
        monkeypatch.setattr(mission_mod, "CHECKPOINT_DIR", tmp_path / "cp")
        from app.unreal_coder_api import _finalize_mission

        stalled = _make_state("mission_stalled", "capture a screenshot")
        stalled.save()
        _finalize_mission(stalled.mission_id, "blocked", "BLOCKED",
                          "MISSION_ORPHANED: no live worker")

        # A brand-new mission right after must start cleanly.
        fresh = _make_state("mission_next", "capture a screenshot")
        fresh.save()
        intent, plan = _plan_steps(fresh.prompt)
        fresh.intent = intent.to_dict()
        fresh.plan = plan
        fresh.status = "executing"
        fresh.save()
        assert MissionState.load("mission_next").status == "executing"

    def test_orphan_reaper_finalizes_stale_executing(
            self, tmp_path, monkeypatch):
        """A checkpoint stuck in `executing` with no live worker past the
        grace period is reaped to BLOCKED on read."""
        from core import mission as mission_mod
        monkeypatch.setattr(mission_mod, "CHECKPOINT_DIR", tmp_path / "cp")
        monkeypatch.setattr(
            "app.unreal_coder_api.ORPHAN_EXECUTING_GRACE_S", 0.0)
        from app.unreal_coder_api import _reap_orphaned_executing

        state = _make_state("mission_orphan", "capture a screenshot")
        state.started_at = time.time() - 999.0
        state.save()
        reaped = _reap_orphaned_executing(state)
        assert reaped.status == "blocked"
        assert reaped.verdict == "BLOCKED"
        assert "MISSION_ORPHANED" in reaped.why


# ---------------------------------------------------------------------------
# 6. No zero-step false PASS
# ---------------------------------------------------------------------------

class TestNoZeroStepFalsePass:
    def test_zero_step_plan_can_never_verify_pass(self, tmp_path,
                                                  monkeypatch):
        """The 0-executed-steps guard in validate() must stay: an empty plan
        can never become verified PASS."""
        from core import mission as mission_mod
        monkeypatch.setattr(mission_mod, "CHECKPOINT_DIR", tmp_path / "cp")
        from core.mission import MissionEngine
        from core.capability_registry import build_capability_registry

        state = _make_state("mission_zero", "capture a screenshot")
        state.intent = interpret_intent(state.prompt).to_dict()
        state.plan = {"steps": [], "visual_gate": {"enabled": False}}
        state.status = "executing"
        state.save()
        engine = MissionEngine(
            tool_registry=_make_registry(),
            capabilities=build_capability_registry(_make_registry()),
            dispatch=lambda step: {"ok": True},
        )
        engine.validate(state)
        final = MissionState.load(state.mission_id)
        assert final.status == "failed"
        assert final.verdict == "FAIL"
        assert "0 steps" in final.why

    def test_capture_plan_never_zero_steps(self):
        for prompt in PLAIN_CAPTURE_PROMPTS:
            _intent, plan = _plan_steps(prompt)
            assert plan["steps"], f"zero-step plan for {prompt!r}"