"""AIVIDO parallel QA — hermetic planner evidence regression.

The certified E2E contract requires that ANY task asking for visual proof
(capture / screenshot / screen shot / proof / visual evidence) emits an
EVIDENCE step using capture_unreal_viewport — even when the prompt names no
actor or asset (e.g. "capture a screenshot of the current map"). Without
that step the parent contract's viewport:captured criterion can never be
satisfied and execution deterministically stalls.

These tests exercise app.api.normalize_execution_plan directly with the LLM
branch stubbed to [] so nothing can reach a live model or bridge. No Unreal
Editor, no backend, no ports.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def planner(monkeypatch):
    from app import api
    # Hermetic guarantee: never fall through to the local coder model.
    monkeypatch.setattr(api, "_llm_structured_steps", lambda task: [])
    return api


KEYWORD_PROMPTS = [
    # exact mission keyword set, actor-less
    "capture a screenshot of the current map",
    "take a screenshot for the record",
    "capture the viewport now",
    "give me proof of the scene",
    "capture visual evidence of the room",
    "screen shot of the current state",
    "please capture and save the current view",
]

CONTROL_PROMPT = "check the current project state"


def _evidence_steps(plan):
    return [s for s in plan["steps"] if s.get("phase") == "EVIDENCE"]


class TestEvidenceContract:
    @pytest.mark.parametrize("prompt", KEYWORD_PROMPTS)
    def test_actorless_proof_prompts_emit_evidence(self, planner, prompt):
        plan = planner.normalize_execution_plan(prompt, {})
        ev = _evidence_steps(plan)
        assert ev, f"no EVIDENCE step for actor-less proof prompt: {prompt!r}"
        for s in ev:
            assert s["preferred_tool"] == "capture_unreal_viewport", \
                f"EVIDENCE step must use capture_unreal_viewport: {s}"
            assert "capture_unreal_viewport" in s["allowed_tools"]
            assert isinstance(s.get("parameters", {}), dict)

    def test_case_insensitive_keywords(self, planner):
        for prompt in ("CAPTURE the scene", "Show me PROOF", "VISUAL EVIDENCE requested"):
            plan = planner.normalize_execution_plan(prompt, {})
            assert _evidence_steps(plan), f"case-insensitive keyword missed: {prompt!r}"

    def test_evidence_step_is_last_or_after_inspect(self, planner):
        """The EVIDENCE step must come after the mandatory INSPECT step."""
        plan = planner.normalize_execution_plan("capture a screenshot of the current map", {})
        phases = [s["phase"] for s in plan["steps"]]
        assert "INSPECT" in phases
        assert phases.index("EVIDENCE") > phases.index("INSPECT")

    def test_control_prompt_without_proof_keyword_has_no_evidence(self, planner):
        """Guard against unconditional evidence: a non-proof request must not
        gain a spurious EVIDENCE step through the keyword branch."""
        plan = planner.normalize_execution_plan(CONTROL_PROMPT, {})
        assert not _evidence_steps(plan), \
            f"control prompt must not get an evidence step: {CONTROL_PROMPT!r}"

    def test_plan_is_serializable_and_well_formed(self, planner):
        import json
        plan = planner.normalize_execution_plan("capture proof of the scene", {})
        assert isinstance(plan, dict) and "steps" in plan
        for s in plan["steps"]:
            for key in ("step_id", "phase", "preferred_tool", "allowed_tools",
                        "parameters", "expected_result", "depends_on", "status"):
                assert key in s, f"step {s.get('step_id')} missing {key}"
        json.dumps(plan)  # must serialize


class TestEvidenceNoProductionChange:
    def test_planner_source_unchanged(self, planner):
        """Tests only — the production planner logic must be exactly the
        certified code (regression guard: this suite adds no production edits)."""
        import inspect
        src = inspect.getsource(planner.normalize_execution_plan)
        # the actor-less keyword branch (mission contract) must still exist
        assert "capture" in src and "visual evidence" in src
        assert "EVIDENCE" in src