"""Mission execution policy — read-only hardening regression tests.

Covers the 9 required cases from the planner-safety hardening mission:

  1. READ_ONLY plan with spawn_actor      -> BLOCKED / PLAN_REJECTED, zero execution
  2. READ_ONLY plan with delete_actor     -> BLOCKED / PLAN_REJECTED, zero execution
  3. READ_ONLY plan with raw execute_python (UNKNOWN) -> BLOCKED, zero execution
  4. READ_ONLY plan with only safe probes -> executes, every tool READ_ONLY, PASS
  5. MUTATING plan with mutation tools    -> allowed, tools execute
  6. UNKNOWN tool during READ_ONLY        -> denied by default
  7. self-fix/recovery cannot inject mutating tools -> boundary guard blocks
  8. dry-run never executes tools
  9. terminal state truthfully reflects the policy violation

Plus the original incident-prompt regression: no matter what the deterministic
planner produces for a READ_ONLY request, a non-read-only tool can never run.

Every test is hermetic: dispatch is a recording spy, no live bridge is touched
(conftest blocks UnrealBridge._send for all unmarked tests anyway).
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from core.mission import MissionState  # noqa: E402
from core.mission_policy import (  # noqa: E402
    MODE_READ_ONLY,
    classify_tool,
    plan_violations,
    policy_snapshot,
    resolve_mission_mode,
)
from core.universal_intent import expand_requirements, interpret_intent  # noqa: E402
from core.universal_planner import MissionPlan, PlanStep  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _spy():
    calls = []

    def spy(step):
        calls.append(str(step.get("preferred_tool") or ""))
        return {"ok": True, "result": {"ok": True,
                                       "tool": step.get("preferred_tool")}}

    return spy, calls


def _step(step_id, phase, intent, tool):
    return PlanStep(step_id=step_id, phase=phase, intent=intent,
                    preferred_tool=tool)


def _execute_with_spy(read_only, steps, prompt="READ ONLY: inspect the project",
                      explicit=True):
    """Run the canonical execution tail (single choke point) with a spy
    dispatch. Returns (response, calls, state)."""
    from app.unreal_coder_api import (
        UnrealCoderRequest,
        _execute_mission_state,
    )
    intent = interpret_intent(prompt)
    reqs = expand_requirements(intent)
    plan = MissionPlan(mission_id="m-policy-test", objective=prompt,
                       intent=intent, requirements=reqs, steps=list(steps))
    state = MissionState(mission_id="m-policy-test", prompt=prompt)
    state.intent = intent.to_dict()
    state.read_only = bool(read_only)
    state.plan = plan.to_dict()
    request = UnrealCoderRequest(
        prompt=prompt,
        read_only=(True if explicit and read_only else
                   (False if explicit else None)),
    )
    spy, calls = _spy()
    resp = _execute_mission_state(
        state, request, {},
        dispatch_bridge=spy,
        capture=lambda: {"ok": True, "result": {"ok": True, "path": "shot.png"}},
        evaluate=lambda c: {"score": 9.0, "defects": []},
        repair=lambda d: {"ok": True},
    )
    return resp, calls, state


# ---------------------------------------------------------------------------
# unit: classification + mode resolution + violations
# ---------------------------------------------------------------------------

class TestClassification:
    def test_read_only_tools_classified(self):
        for tool in ("inspect_project", "get_project_identity",
                     "list_level_actors", "capture_unreal_viewport",
                     "unreal_status"):
            assert classify_tool(tool) == "READ_ONLY", tool

    def test_mutating_tools_classified(self):
        for tool in ("spawn_actor", "delete_actor", "move_actor",
                     "save_level", "import_asset", "run_powershell",
                     "set_character_transform", "open_map"):
            assert classify_tool(tool) == "MUTATING", tool

    def test_unknown_denied_by_default(self):
        # Raw Python / arbitrary execution and any unlisted tool are UNKNOWN,
        # which READ_ONLY missions deny by default.
        for tool in ("execute_python", "run_code", "some_new_tool_2026"):
            assert classify_tool(tool) == "UNKNOWN", tool

    def test_incident_prompt_resolves_read_only_despite_execute_intent(self):
        # The root-cause prompt: the word "spawn" (inside "do NOT spawn")
        # made the LLM-intent classifier choose execute mode. The canonical
        # mode resolution must still yield READ_ONLY via strong markers.
        prompt = ("READ ONLY: inspect the project and report its status. "
                  "Do NOT spawn, do NOT modify anything.")
        assert resolve_mission_mode(prompt) == MODE_READ_ONLY
        # And the explicit request flag is authoritative over everything.
        assert resolve_mission_mode(
            "spawn a cool actor", explicit_read_only=True) == MODE_READ_ONLY
        assert resolve_mission_mode(
            "read only", explicit_read_only=False) != MODE_READ_ONLY

    def test_plan_violations_only_for_read_only(self):
        steps = [_step("a", "INSPECT", "inspect", "inspect_project"),
                 _step("b", "EDIT", "spawn", "spawn_actor")]
        assert len(plan_violations(True, [s.to_dict() for s in steps])) == 1
        assert plan_violations(False, [s.to_dict() for s in steps]) == []

    def test_policy_snapshot_truthful(self):
        class S:
            read_only = True
            plan = {"steps": [
                _step("a", "INSPECT", "inspect", "inspect_project").to_dict(),
                _step("b", "EDIT", "spawn", "spawn_actor").to_dict()]}
        snap = policy_snapshot(S())
        assert snap["mode"] == "READ_ONLY"
        assert snap["verdict"] == "PLAN_REJECTED"
        assert snap["blocked_tools"] == ["spawn_actor"]


# ---------------------------------------------------------------------------
# cases 1-3: READ_ONLY plan with a non-read-only step -> BLOCKED, zero calls
# ---------------------------------------------------------------------------

class TestReadOnlyPlanGate:
    @pytest.mark.parametrize("tool", ["spawn_actor", "delete_actor",
                                      "execute_python"])
    def test_read_only_plan_rejected_with_zero_execution(self, tool):
        steps = [_step("s1", "INSPECT", "inspect", "inspect_project"),
                 _step("s2", "EDIT", "mutate", tool)]
        resp, calls, state = _execute_with_spy(True, steps)
        assert resp["status"] == "blocked"
        assert resp["verdict"] == "PLAN_REJECTED"
        assert resp["policy"]["mode"] == "READ_ONLY"
        assert resp["policy"]["verdict"] == "PLAN_REJECTED"
        assert tool in resp["policy"]["blocked_tools"]
        assert tool in resp["why"]
        assert calls == [], "no step may execute on a rejected read-only plan"
        assert state.completed_step_ids == []


# ---------------------------------------------------------------------------
# case 4: READ_ONLY plan with only safe probes -> executes, PASS, all READ_ONLY
# ---------------------------------------------------------------------------

class TestReadOnlyCleanPlan:
    def test_read_only_safe_plan_runs_to_pass(self):
        steps = [_step("s1", "INSPECT", "inspect", "inspect_project"),
                 _step("s2", "INSPECT", "identity", "get_project_identity"),
                 _step("s3", "VALIDATE", "status", "unreal_status")]
        resp, calls, _state = _execute_with_spy(True, steps)
        assert resp["status"] == "complete"
        assert resp["verdict"] == "PASS"
        assert len(calls) == 3
        assert all(classify_tool(t) == "READ_ONLY" for t in calls), calls
        assert resp["policy"]["verdict"] == "OK"


# ---------------------------------------------------------------------------
# case 5: MUTATING mission with mutation tools -> allowed
# ---------------------------------------------------------------------------

class TestMutatingAllowed:
    def test_mutating_plan_executes_mutation_tools(self):
        steps = [_step("s1", "EDIT", "spawn", "spawn_actor"),
                 _step("s2", "VALIDATE", "verify", "verify_character_visible")]
        resp, calls, _state = _execute_with_spy(
            False, steps, prompt="Spawn a test actor then verify it")
        assert resp["status"] == "complete"
        assert resp["verdict"] == "PASS"
        assert "spawn_actor" in calls
        assert resp["policy"]["mode"] != "READ_ONLY"
        assert resp["policy"]["verdict"] == "ALLOWED"


# ---------------------------------------------------------------------------
# case 7: the final execution boundary blocks any injected mutating step
# (recovery / self-fix / resume steps also go through this same wrapper)
# ---------------------------------------------------------------------------

class TestBoundaryGuard:
    def test_guarded_dispatch_blocks_injected_mutation(self):
        from app.unreal_coder_api import policy_guarded_dispatch
        spy, calls = _spy()
        guarded = policy_guarded_dispatch(True, spy)
        injected = {"preferred_tool": "spawn_actor",
                    "parameters": {"label": "UA_env_rogue"}}
        out = guarded(injected)
        assert out["ok"] is False
        assert out.get("policy_blocked") is True
        assert out["safety"] == "MUTATING"
        assert "POLICY_BLOCKED" in out["error"]
        assert calls == []

        ok = guarded({"preferred_tool": "inspect_project", "parameters": {}})
        assert ok["ok"] is True
        assert calls == ["inspect_project"]

    def test_unknown_tool_blocked_at_boundary(self):
        from app.unreal_coder_api import policy_guarded_dispatch
        spy, calls = _spy()
        guarded = policy_guarded_dispatch(True, spy)
        out = guarded({"preferred_tool": "execute_python", "parameters": {}})
        assert out["ok"] is False
        assert out.get("policy_blocked") is True
        assert out["safety"] == "UNKNOWN"
        assert calls == []

    def test_mutating_mission_boundary_passes_through(self):
        from app.unreal_coder_api import policy_guarded_dispatch
        spy, calls = _spy()
        guarded = policy_guarded_dispatch(False, spy)
        out = guarded({"preferred_tool": "spawn_actor", "parameters": {}})
        assert out["ok"] is True
        assert calls == ["spawn_actor"]


# ---------------------------------------------------------------------------
# case 8: dry-run never executes tools, always exposes safety + blocked marks
# ---------------------------------------------------------------------------

class TestDryRunContract:
    @pytest.fixture()
    def dry_app(self, monkeypatch):
        from fastapi import FastAPI
        from app.unreal_coder_api import register_unreal_coder_api

        class FakePlanner:
            def build_plan(self, intent_obj, requirements_obj, _ctx):
                steps = [_step("s1", "INSPECT", "inspect", "inspect_project"),
                         _step("s2", "EDIT", "spawn", "spawn_actor")]
                return MissionPlan("m-dry", "test", intent_obj,
                                   requirements_obj, steps=steps)

        monkeypatch.setattr(
            "app.unreal_coder_api.build_universal_planner",
            lambda registry: FakePlanner())

        app = FastAPI()
        register_unreal_coder_api(
            app, tool_registry=lambda: {},
            capture=lambda: {"ok": True, "result": {"ok": True, "path": "x.png"}},
            evaluate=lambda c: {"score": 9.0, "defects": []},
            repair=lambda d: {"ok": True})
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client

    def test_read_only_dry_run_rejects_and_never_executes(self, dry_app):
        resp = dry_app.post("/api/unreal-coder", json={
            "prompt": "READ ONLY: inspect the project",
            "read_only": True,
            "dry_run": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "blocked"
        assert data["verdict"] == "PLAN_REJECTED"
        assert data["policy"]["verdict"] == "PLAN_REJECTED"
        assert "spawn_actor" in data["policy"]["blocked_tools"]
        assert data["resumable"] is False
        by_tool = {s["tool"]: s for s in data["plan"]["steps"]}
        assert by_tool["spawn_actor"]["safety"] == "MUTATING"
        assert by_tool["spawn_actor"]["blocked"] is True
        assert by_tool["inspect_project"]["safety"] == "READ_ONLY"
        assert by_tool["inspect_project"]["blocked"] is False

    def test_mutating_dry_run_plans_but_never_executes(self, dry_app):
        resp = dry_app.post("/api/unreal-coder", json={
            "prompt": "Spawn a test actor",
            "read_only": False,
            "dry_run": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        # Dry-run returns the plan (planning state) — never transitions into
        # execution: no step has run, and no tool was dispatched.
        assert data["status"] == "planning"
        assert data["policy"]["mode"] != "READ_ONLY"
        assert data["policy"]["verdict"] == "ALLOWED"
        by_tool = {s["tool"]: s for s in data["plan"]["steps"]}
        assert by_tool["spawn_actor"]["blocked"] is False


# ---------------------------------------------------------------------------
# case 9 + incident regression: terminal state truthfully reflects violations
# ---------------------------------------------------------------------------

class TestIncidentRegression:
    def test_terminal_state_truthful(self):
        steps = [_step("s1", "INSPECT", "inspect", "inspect_project"),
                 _step("s2", "EDIT", "spawn", "spawn_actor")]
        resp, calls, state = _execute_with_spy(True, steps)
        assert state.status == "blocked"
        assert state.verdict == "PLAN_REJECTED"
        assert resp["status"] == "blocked"
        assert resp["verdict"] == "PLAN_REJECTED"
        assert resp["policy"]["reason"]
        assert resp["completed_work"]["steps_completed"] == 0
        assert resp["resumable"] is False
        assert calls == []

    def test_incident_prompt_real_planner_never_executes_mutation(self):
        """The exact incident prompt class, with the REAL deterministic
        planner over the REAL tool registry. Whatever the planner produces,
        a READ_ONLY request can never execute a non-read-only tool."""
        from app import api
        from core.universal_planner import build_universal_planner
        prompt = ("READ ONLY: inspect the project and report its status. "
                  "Do NOT spawn, do NOT modify anything, do NOT delete "
                  "anything.")
        intent = interpret_intent(prompt)
        reqs = expand_requirements(intent)
        plan = build_universal_planner(api.REGISTRY).build_plan(intent, reqs, None)
        assert len(plan.steps) > 0, "planner produced an empty plan"
        non_read_only = [s.preferred_tool for s in plan.steps
                         if classify_tool(s.preferred_tool) != "READ_ONLY"]

        resp, calls, _state = _execute_with_spy(True, plan.steps, prompt=prompt)

        assert resp["policy"]["mode"] == "READ_ONLY"
        if non_read_only:
            # Mis-planned like the incident -> rejected up front, zero work.
            assert resp["status"] == "blocked"
            assert resp["verdict"] == "PLAN_REJECTED"
            assert calls == []
            assert set(non_read_only) <= set(resp["policy"]["blocked_tools"])
        else:
            # Safely planned -> only READ_ONLY tools may have run.
            assert all(classify_tool(t) == "READ_ONLY" for t in calls), calls
            assert resp["status"] in ("complete", "failed", "blocked")