"""Regression suite for the AvaLive Blueprint compile failure + null stall.

Reproduces the exact live failure (task 4cc34db6-daa6-4acd-a1c1-b40a475ae85e):
a /Game/Maps/ path was treated as a Blueprint asset_path, compile_blueprint
failed, and EXECUTION_STALLED was emitted with "stall_reason": null.

Proves:
  * the planner never extracts Level/Map paths as Blueprint asset_paths
  * create_blueprint / compile_blueprint produce structured evidence and never
    claim success for an existing World/Level or a wrong object kind
  * a compile failure triggers bounded automatic recovery whose retries ALWAYS
    change the strategy (max 3 attempts, never an identical repeat)
  * an exhausted failure ends in a non-null structured STALL_FAILED_MANDATORY_STEP
    reason carrying failed_step_id / failed_tool / last_error / recovery_attempts
    / pending_acceptance_criteria
  * a successful retry lets the parent task continue to COMPLETE
  * COMPLETE stays forbidden while AvaLive mandatory criteria are pending
"""
import uuid
from unittest.mock import Mock, patch

from app import api
from core import task_goal

# The exact AvaLive continuation prompt that triggered the live regression.
AVALIVE_PROMPT = (
    "CONTINUE AVALIVE NOW - FULL PRODUCT BUILD.\n"
    "PROJECT:\nC:\\Users\\Shadow\\Desktop\\AvaLive\\AvaLive.uproject\n"
    "MAP:\n/Game/Maps/AvaLive_Main\n"
    "GOAL:\nFinish the complete AvaLive experience end-to-end with verified "
    "real-time Ollama chat, photorealistic avatar, cinematic environment, and "
    "polished UI, save everything, run in Unreal, reopen verification, and "
    "final screenshot verification."
)


def _goal(prompt):
    return task_goal.build_acceptance_contract(prompt, dict(api._default_project_context()))


def _avlive_steps(compile_path="/Game/Maps/AvaLive_Main"):
    """Hand-crafted plan mirroring the observed AvaLive plan (start statuses
    completed for inspect/ping/create, exactly like the live failure)."""
    def step(step_id, phase, intent, tool, params=None, expected=None, deps=None):
        return {
            "step_id": step_id, "phase": phase, "intent": intent,
            "action_category": intent, "preferred_tool": tool,
            "allowed_tools": [tool], "target_type": "blueprint",
            "target_resource": compile_path, "parameters": params or {},
            "expected_result": expected or {}, "validation_tool": None,
            "validation_parameters": {}, "depends_on": deps or [],
            "disposable": False, "status": "completed" if step_id != "compile_save" else "pending",
        }
    return {
        "goal": "AvaLive",
        "success_criteria": [],
        "steps": [
            step("inspect_project", "INSPECT", "inspect_project", "inspect_project"),
            step("ping", "INSPECT", "unreal_ping", "unreal_ping", deps=["inspect_project"]),
            step("create_blueprint", "EDIT", "create_blueprint", "create_blueprint",
                 {"asset_path": compile_path, "parent_class": "Actor"}, deps=["ping"]),
            step("compile_save", "BUILD", "compile_blueprint", "compile_blueprint",
                 {"asset_path": compile_path}, deps=["create_blueprint"]),
            step("final_evidence", "EVIDENCE", "capture_unreal_viewport", "capture_unreal_viewport",
                 deps=["compile_save"]),
        ],
    }


def _state(steps, goal):
    return {
        "id": str(uuid.uuid4()),
        "task": AVALIVE_PROMPT,
        "task_goal": goal,
        "project_context": dict(api._default_project_context()),
        "phase": "PLAN", "current_phase": "PLAN", "current_step": 0,
        "completed_steps": [], "failed_step": None, "retry_count": 0,
        "validation_result": None, "created_resources": [],
        "processed_dispatch_ids": [], "fix_pending": False, "fix_step_id": None,
        "retry_pending": False, "retry_validation_step_id": None,
        "max_retries": 3, "max_tool_calls": 40, "model_messages": [], "trace": [],
        "failed_calls": {}, "verification_pending": False, "successful_calls": 0,
        "final_rejections": 0, "step": 0, "tool_call_count": 0,
        "state": "PLANNING", "current_action": None, "start_ts": None, "end_ts": None,
        "plan": steps,
    }


def _run(state, fake, goal):
    """Run the deterministic loop against `fake` and return (result, calls)."""
    state["task_goal"] = goal
    calls = []

    def recorder(spec, args, timeout_seconds=60):
        calls.append((spec.name, dict(args)))
        return fake(spec, args, timeout_seconds=timeout_seconds)

    api.execution_state = state
    with patch.object(api, "call_tool_hard_timeout", side_effect=recorder):
        result = api.run_execution_until_pause()
    return result, calls


def _ok(name, args):
    if name == "inspect_project":
        return {"ok": True, "result": {"project": "AvaLive"}}
    if name == "unreal_ping":
        return {"ok": True, "result": {"ok": True}}
    if name == "create_blueprint":
        return {"ok": True, "result": {"ok": True, "asset_path": args.get("asset_path"), "asset_type": "Blueprint"}}
    if name == "capture_unreal_viewport":
        return {"ok": True, "result": {"ok": True, "path": "proof.png"}}
    if name == "save_level":
        return {"ok": True, "result": {"ok": True, "saved": True}}
    if name == "list_level_actors":
        return {"ok": True, "result": {"ok": True, "actors": []}}
    return {"ok": True, "result": {"ok": True}}


# ---------------------------------------------------------------------------
# Planner regression: the map path must never become a Blueprint asset_path.
# ---------------------------------------------------------------------------

def test_planner_never_treats_map_path_as_blueprint_asset():
    plan = api.normalize_execution_plan(AVALIVE_PROMPT, {})
    tools = [s["preferred_tool"] for s in plan["steps"]]
    # The observed regression created create_blueprint + compile_blueprint
    # steps against /Game/Maps/AvaLive_Main (a World). After the fix neither
    # step exists because the map is a Level reference, not a Blueprint path.
    assert "create_blueprint" not in tools or all(
        s["parameters"].get("asset_path") != "/Game/Maps/AvaLive_Main"
        for s in plan["steps"] if s["preferred_tool"] == "create_blueprint"
    )
    assert all(
        s["parameters"].get("asset_path") != "/Game/Maps/AvaLive_Main"
        for s in plan["steps"]
    )
    params = api._extract_task_parameters(AVALIVE_PROMPT)
    assert params["asset_path"] is None, "MAP:/Game/Maps/... must not be extracted as a Blueprint asset"


def test_planner_still_extracts_real_blueprint_paths():
    params = api._extract_task_parameters(
        "Create /Game/AgentGraduation/BP_FinalSelfFixProbe and compile it."
    )
    assert params["asset_path"] == "/Game/AgentGraduation/BP_FinalSelfFixProbe"


# ---------------------------------------------------------------------------
# Tool regression: structured evidence, wrong-kind rejection, never pass just
# because Python executed.
# ---------------------------------------------------------------------------

def test_compile_blueprint_rejects_level_path_without_touching_bridge():
    from tools.unreal.blueprint_tools import BlueprintTools

    bridge = Mock()
    result = BlueprintTools(bridge).compile_blueprint("/Game/Maps/AvaLive_Main")
    assert result["ok"] is False
    assert result["code"] == "INVALID_BLUEPRINT_PATH"
    assert result["asset_type"] == "World (Level/Map path)"
    assert result["verified"] is False
    bridge.execute_python.assert_not_called()
    assert result["compile_api"] == "BlueprintEditorLibrary.compile_blueprint"


def test_create_blueprint_script_rejects_existing_non_blueprint():
    # The generated script must refuse to report success for a path occupied
    # by a World/Level (the exact live create_blueprint false-success bug).
    source = open("tools/unreal/blueprint_tools.py", encoding="utf-8-sig").read()
    assert 'not in ("Blueprint", "WidgetBlueprint")' in source
    assert '"WRONG_ASSET_TYPE"' in source
    assert '"preserved"' in source


def test_widget_blueprint_compile_verified():
    bridge = Mock()
    bridge.execute_python.return_value = {"ok": True, "result": {
        "ok": True, "code": None, "asset_path": "/Game/UI/WBP_Panel",
        "asset_type": "WidgetBlueprint", "compile_api": "BlueprintEditorLibrary.compile_blueprint",
        "asset_found": True, "is_blueprint": True, "compile_called": True,
        "compile_status": "<BlueprintStatus.BS_UP_TO_DATE: 3>", "save_ok": True,
        "verified": True, "errors": [], "recoverable": False,
    }}
    from tools.unreal.blueprint_tools import BlueprintTools
    result = BlueprintTools(bridge).compile_blueprint("/Game/UI/WBP_Panel")
    assert result["result"]["verified"] is True
    assert result["result"]["asset_type"] == "WidgetBlueprint"


def test_generated_class_confusion_has_struct_diagnostics():
    source = open("tools/unreal/blueprint_tools.py", encoding="utf-8-sig").read()
    assert "BlueprintGeneratedClass" in source
    assert "CDO/instance" in source.lower() or "cdo" in source.lower()
    assert "WRONG_ASSET_TYPE" in source


def test_compile_error_not_reported_as_success_even_when_python_ran():
    bridge = Mock()
    bridge.execute_python.return_value = {"ok": True, "result": {
        "ok": False, "code": "BLUEPRINT_COMPILE_FAILED",
        "asset_found": True, "is_blueprint": True, "compile_called": True,
        "compile_status": "<BlueprintStatus.BS_Error: 1>", "save_ok": False,
        "verified": False, "errors": ["node connection broken"],
    }}
    from tools.unreal.blueprint_tools import BlueprintTools
    result = BlueprintTools(bridge).compile_blueprint("/Game/Blueprints/BP_Probe")
    assert result["result"]["ok"] is False
    assert result["result"]["verified"] is False


# ---------------------------------------------------------------------------
# Loop regression: the exact AvaLive failure -> structured stall, never null.
# ---------------------------------------------------------------------------

def test_exhausted_compile_failure_stalls_with_non_null_structured_reason():
    api.events.clear()
    goal = _goal(AVALIVE_PROMPT)
    state = _state(_avlive_steps(), goal)
    assert goal["pending_criteria"], "AvaLive parent must keep mandatory criteria"

    def fake(spec, args, timeout_seconds=60):
        name = spec.name
        if name == "compile_blueprint":
            # Simulate the exact live result for a Level/Map target.
            return {"ok": False, "code": "INVALID_BLUEPRINT_PATH",
                    "asset_path": args.get("asset_path"),
                    "errors": ["Refusing to compile a Level/Map as a Blueprint"]}
        return _ok(name, args)

    result, calls = _run(state, fake, goal)

    compile_calls = [args for name, args in calls if name == "compile_blueprint"]
    assert len(compile_calls) == 3, compile_calls
    # Recovery must NEVER repeat the identical failed compile call: the
    # strategies change on every retry.
    strategies = [args.get("strategy") for args in compile_calls]
    assert strategies == [None, "rescan", "repair"], strategies

    # The parent goal must remain incomplete...
    assert goal["pending_criteria"]
    # ...COMPLETE must be forbidden...
    assert result["terminal"] != "PASS"
    assert not any(e.get("type") == "complete" for e in api.events)
    # ...and the stall reason must be non-null and structured.
    assert result["state"] == "failed"
    assert result["stall_reason"] == api.STALL_FAILED_MANDATORY_STEP
    assert state["stall_reason"] == api.STALL_FAILED_MANDATORY_STEP
    assert result["stall_detail"] is not None

    detail = result["stall_detail"]
    assert detail["failed_step_id"] == "compile_save"
    assert detail["failed_tool"] == "compile_blueprint"
    assert "Level/Map" in detail["last_error"]
    assert detail["recovery_attempts"] == 3
    assert detail["pending_acceptance_criteria"]

    # The emitted EXECUTION_STALLED event must never carry stall_reason null.
    stalled = [e for e in api.events if e.get("title") == "EXECUTION_STALLED"]
    assert len(stalled) == 1
    assert stalled[0]["detail"]["stall_reason"] == api.STALL_FAILED_MANDATORY_STEP
    assert stalled[0]["detail"].get("stall_detail", {}).get("failed_step_id") == "compile_save"


def test_successful_compile_retry_lets_parent_continue():
    api.events.clear()
    goal = _goal(
        "Create a compiled Blueprint probe at /Game/Blueprints/BP_Probe, "
        "then save the level and capture a screenshot."
    )
    steps = {
        "goal": "bp",
        "steps": [
            {"step_id": "inspect", "phase": "INSPECT", "intent": "inspect_project",
             "preferred_tool": "inspect_project", "allowed_tools": ["inspect_project"],
             "parameters": {}, "expected_result": {}, "depends_on": [], "disposable": False,
             "status": "pending"},
            {"step_id": "create", "phase": "EDIT", "intent": "create_blueprint",
             "preferred_tool": "create_blueprint", "allowed_tools": ["create_blueprint"],
             "parameters": {"asset_path": "/Game/Blueprints/BP_Probe", "parent_class": "Actor"},
             "expected_result": {}, "depends_on": ["inspect"], "disposable": False,
             "status": "pending"},
            {"step_id": "compile", "phase": "BUILD", "intent": "compile_blueprint",
             "preferred_tool": "compile_blueprint", "allowed_tools": ["compile_blueprint"],
             "parameters": {"asset_path": "/Game/Blueprints/BP_Probe"},
             "expected_result": {}, "depends_on": ["create"], "disposable": False,
             "status": "pending"},
            {"step_id": "save_build", "phase": "BUILD", "intent": "save_level",
             "preferred_tool": "save_level", "allowed_tools": ["save_level"],
             "parameters": {}, "expected_result": {}, "depends_on": ["compile"],
             "disposable": False, "status": "pending"},
            {"step_id": "evidence", "phase": "EVIDENCE", "intent": "capture_unreal_viewport",
             "preferred_tool": "capture_unreal_viewport", "allowed_tools": ["capture_unreal_viewport"],
             "parameters": {}, "expected_result": {}, "depends_on": ["save_build"],
             "disposable": False, "status": "pending"},
        ],
    }
    state = _state(steps, goal)
    state["plan"] = steps

    def fake(spec, args, timeout_seconds=60):
        name = spec.name
        if name == "compile_blueprint":
            if args.get("strategy") == "rescan":
                # The changed strategy makes the compile succeed.
                return {"ok": True, "result": {"ok": True, "verified": True,
                        "compile_status": "<BlueprintStatus.BS_UP_TO_DATE: 3>", "save_ok": True}}
            return {"ok": False, "errors": ["transient compile failure"]}
        return _ok(name, args)

    result, calls = _run(state, fake, goal)

    assert result["terminal"] == "PASS"
    assert result["state"] == "complete"
    assert not any(e.get("title") == "EXECUTION_STALLED" for e in api.events)
    assert any(e.get("type") == "complete" for e in api.events)
    strategies = [args.get("strategy") for name, args in calls if name == "compile_blueprint"]
    assert strategies == [None, "rescan"], strategies
    # The recovered compile step and every descendant completed -> parent goal
    # criteria cleared and COMPLETE was allowed.
    compile_step = next(s for s in steps["steps"] if s["step_id"] == "compile")
    assert compile_step["status"] == "completed"
    # reconcile_step replaces the goal dict with a fresh save; the live goal is
    # the one the execution state holds. Its criteria must all be satisfied.
    assert task_goal.contract_complete(state["task_goal"]) is True


def test_complete_forbidden_while_avlive_criteria_pending_even_when_steps_done():
    # Even if every executable step finished, the deterministic gate must keep
    # the run from COMPLETE while AvaLive mandatory criteria are pending, and
    # the stall must carry a non-null structured reason.
    api.events.clear()
    goal = _goal(AVALIVE_PROMPT)
    for completed in list(goal["pending_criteria"])[:2]:
        goal = task_goal.update_task_goal(goal, completed=[completed])
    assert goal["pending_criteria"]  # many criteria still pending

    steps = {"steps": [
        {"step_id": "a", "phase": "INSPECT", "intent": "inspect_project",
         "preferred_tool": "inspect_project", "status": "completed", "disposable": False},
    ]}
    state = _state(steps, goal)
    state["plan"] = steps
    state["validation_result"] = "passed"

    result, _ = _run(state, lambda spec, args, timeout_seconds=60: {"ok": True, "result": {}}, goal)
    assert result["terminal"] != "PASS"
    assert result["state"] == "failed"
    assert result["stall_reason"] is not None
    assert result["stall_reason"] == api.STALL_NO_PROGRESS or result["stall_reason"] == api.STALL_FAILED_MANDATORY_STEP
    assert result["stall_detail"]["pending_acceptance_criteria"]
    assert not any(e.get("type") == "complete" for e in api.events)