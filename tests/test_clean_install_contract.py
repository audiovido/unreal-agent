"""RC1.1 clean-install + viewport execution planning regressions.

Defect 1: a fresh clone + fresh venv failed with
`ModuleNotFoundError: No module named 'requests'` because the authoritative
dependency contract omitted it. tests/test_clean_install_contract.py now
pins the runtime import closure.

Defect 2: explicit viewport capture/proof prompts (mode=execute) produced a
0-step plan through the universal intent/planner pipeline (the path used by
/api/unreal-coder and the session runner), which the truthful zero-step
guard then failed. The planner must emit a real READ-ONLY
capture_unreal_viewport EVIDENCE step for such prompts.

All tests are hermetic: no Unreal, no backend, no ports, no vendored
packages.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.universal_intent import expand_requirements, interpret_intent
from core.universal_planner import build_universal_planner
from core.tool_registry import build_registry
from core import orchestrator


# ---------------------------------------------------------------------------
# Defect 1 — clean dependency contract
# ---------------------------------------------------------------------------

# Every third-party top-level import the runtime performs (mirrors
# requirements.txt; keep in sync — the test below fails if drift appears).
RUNTIME_IMPORT_CONTRACT = (
    "fastapi", "uvicorn", "PIL", "numpy", "pydantic", "requests", "rich",
)


@pytest.mark.parametrize("module", RUNTIME_IMPORT_CONTRACT)
def test_runtime_import_contract_succeeds(module):
    """A clean dependency contract must let every runtime import succeed."""
    mod = importlib.import_module(module)
    assert mod is not None


def test_requirements_file_lists_full_contract():
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    for pkg in ("fastapi", "uvicorn", "pillow", "numpy", "pydantic",
                "requests", "rich"):
        assert pkg in text, f"requirements.txt missing runtime dep: {pkg}"


# ---------------------------------------------------------------------------
# Defect 2 — planner emits a real read-only capture step
# ---------------------------------------------------------------------------

CAPTURE_PROMPTS = [
    "Capture the current Unreal viewport",
    "Take a screenshot of the current viewport as evidence",
    "Return visual proof of the current Unreal viewport",
]

EXACT_CLEAN_CLONE_PROMPT = (
    "Capture the CURRENT Unreal Editor viewport from the live AividoHQ "
    "project and return the captured viewport as real evidence. "
    "This is an execution task, not chat. "
    "Read-only: do not modify the project."
)

UNRELATED_CHAT_PROMPT = (
    "What is the capital of France, and how does Unreal handle "
    "level streaming between sublevels?"
)

MUTATING_TOOLS_DENYLIST = {
    "spawn_actor", "delete_actor", "set_actor_location", "run_powershell",
    "open_project", "create_project", "write_text_file", "import_asset",
}


def _plan_for(prompt: str):
    intent = interpret_intent(prompt)
    requirements = expand_requirements(intent)
    registry = build_registry(
        orchestrator.discover_projects, orchestrator.inspect_project,
        orchestrator.open_project, orchestrator.create_project,
        orchestrator.read_text_file, orchestrator.write_text_file,
        orchestrator.run_powershell, orchestrator.unreal_status,
        bridge=None)
    planner = build_universal_planner(registry)
    plan = planner.build_plan(intent, requirements, {})
    return intent, plan.to_dict()


class TestCapturePlanning:
    @pytest.mark.parametrize("prompt", CAPTURE_PROMPTS)
    def test_capture_prompts_plan_real_capture_step(self, prompt):
        intent, plan = _plan_for(prompt)
        assert plan["steps"], f"zero-step plan for capture prompt: {prompt!r}"
        capture_steps = [s for s in plan["steps"]
                         if s.get("preferred_tool") == "capture_unreal_viewport"]
        assert capture_steps, \
            f"no capture_unreal_viewport step for prompt: {prompt!r}"
        # the requested evidence is the deliverable: an EVIDENCE phase step
        assert any(s.get("phase") == "EVIDENCE" for s in capture_steps)

    @pytest.mark.parametrize("prompt", CAPTURE_PROMPTS)
    def test_capture_prompts_are_read_only_compatible(self, prompt):
        intent, plan = _plan_for(prompt)
        assert intent.read_only is True, prompt
        assert intent.mode == "execute", prompt
        # no mutating tool anywhere in the plan (read-only compatible)
        tools = {s.get("preferred_tool") for s in plan["steps"]}
        assert not (tools & MUTATING_TOOLS_DENYLIST), \
            f"mutating tools in read-only capture plan: {tools}"

    def test_exact_clean_clone_prompt_plans_capture(self):
        intent, plan = _plan_for(EXACT_CLEAN_CLONE_PROMPT)
        assert intent.mode == "execute"
        assert intent.capture_only is True
        tools = [s.get("preferred_tool") for s in plan["steps"]]
        assert "capture_unreal_viewport" in tools
        assert plan["steps"], "zero-step plan for the clean-clone prompt"

    def test_unrelated_chat_gets_no_capture_step(self):
        intent, plan = _plan_for(UNRELATED_CHAT_PROMPT)
        assert intent.mode == "chat"
        tools = [s.get("preferred_tool") for s in plan["steps"]]
        assert "capture_unreal_viewport" not in tools, tools

    def test_capture_intent_dict_flags_flow_to_policy(self):
        """The serialized intent must carry capture_only so API-layer mode
        resolution can keep the mission read-only."""
        intent = interpret_intent("Capture the current Unreal viewport")
        assert intent.to_dict()["capture_only"] is True
        assert intent.to_dict()["read_only"] is True


class TestTruthfulGuardsPreserved:
    def test_zero_step_execute_missions_fail_truthfully(self):
        """The 0-completed-steps guard must stay: an execute mission that
        completed nothing can never be verified PASS."""
        from core import mission as mission_mod
        src = mission_mod.__dict__  # noqa: F841
        import inspect
        source = inspect.getsource(mission_mod)
        assert "0 executed steps" in source or (
            "Mission executed 0 steps" in source), \
            "zero-step FAIL guard removed from mission validation"

    def test_request_tool_missing_gate_intact(self):
        """Explicit unsatisfiable tool requests must still fail truthfully
        up front (REQUESTED_TOOL_MISSING behavior from release-95)."""
        from core.session_execution import _extract_requested_tools
        got = _extract_requested_tools(
            "read only: call the tool named definitely_not_a_real_tool_xyz "
            "and report its exact result")
        assert got == {"definitely_not_a_real_tool_xyz"}
        # and the gate itself still exists in the run path source
        import inspect
        from core import session_execution
        source = inspect.getsource(session_execution)
        assert "REQUESTED_TOOL_MISSING" in source


class TestCaptureEvidenceEmission:
    def test_capture_mission_records_real_evidence(self, tmp_path):
        """A completed capture/proof mission must carry the real captured
        PNG path in state.evidence (get_evidence never empty)."""
        from core.mission import MissionEngine, MissionState

        state = MissionState(mission_id="mission_test_capture",
                             prompt="Capture the current Unreal viewport")
        state.intent = {
            "capture_only": True, "mode": "execute", "read_only": True,
        }
        state.plan = {"steps": [
            {"step_id": "viewport_evidence", "phase": "EVIDENCE",
             "preferred_tool": "capture_unreal_viewport"},
        ]}
        state.completed_step_ids = ["viewport_evidence"]
        state.step_results = {"viewport_evidence": {
            "ok": True, "tool": "capture_unreal_viewport",
            # real shape: bridge envelope nested around the tool result
            "result": {"ok": True, "message": "Python executed",
                       "result": {"ok": True,
                                  "path": str(tmp_path / "viewport_latest.png"),
                                  "size": 1351837,
                                  "capture_source": "NativeEditorViewport"},
                       "stdout": ""},
        }}

        engine = MissionEngine.__new__(MissionEngine)
        MissionEngine._emit_capture_evidence(engine, state)

        ev = [e for e in state.evidence if e.get("kind") == "viewport_capture"]
        assert ev, "capture mission produced no evidence entry"
        assert ev[0]["ok"] is True
        assert ev[0]["path"].endswith("viewport_latest.png")
        assert ev[0]["bytes"] == 1351837
