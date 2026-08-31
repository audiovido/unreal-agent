from app.api import normalize_execution_plan

TASK = "Create /Game/AgentGraduation/BP_FinalSelfFixProbe. Add String variable AgentGraduationMarker. Initially set it to WRONG_VALUE. Expected value is EXPECTED_VALUE. Validate it. Delete the probe."


def test_normalizes_executable_steps_and_preserves_parameters():
    plan = normalize_execution_plan(TASK, {"goal": "x", "steps": ["inspect", "prepare", "validate"]})
    steps = plan["steps"]
    assert [s["preferred_tool"] for s in steps] == ["inspect_project", "create_blueprint", "add_blueprint_variable", "set_blueprint_variable_default", "compile_blueprint", "get_blueprint_variable_default", "capture_unreal_viewport", "delete_asset"]
    create = steps[1]
    assert create["target_resource"] == "/Game/AgentGraduation/BP_FinalSelfFixProbe"
    assert steps[2]["parameters"]["variable_type"] == "String"
    assert steps[0]["preferred_tool"] == "inspect_project"
    assert steps[3]["parameters"]["value"] == "WRONG_VALUE"
    assert steps[5]["expected_result"]["expected"] == "EXPECTED_VALUE"
    assert steps[-1]["disposable"] is True


def test_normalized_steps_have_single_tool_contract():
    plan = normalize_execution_plan(TASK, {})
    for step in plan["steps"]:
        assert step["preferred_tool"] in step["allowed_tools"]
        assert step["status"] == "pending"

def test_normalizes_new_project_lifecycle_without_model_fallback():
    task = (
        "Create a new disposable Unreal project named UA_ProjectCreation_Test, "
        "open it in Unreal Engine, create a visible cube actor named "
        "UA_NewProjectMarker in the default level, save everything, and verify "
        "that the actor exists before completing."
    )
    plan = normalize_execution_plan(task, {})
    assert [s["preferred_tool"] for s in plan["steps"]] == [
        "create_project", "inspect_project", "create_default_level",
        "get_project_identity", "spawn_actor", "save_level", "get_actor",
        "validate_project_creation",
    ]
    assert plan["steps"][0]["parameters"]["project_name"] == "UA_ProjectCreation_Test"
    assert plan["steps"][4]["parameters"]["mesh_asset"] == "/Engine/BasicShapes/Cube.Cube"
    assert plan["steps"][-1]["expected_result"] == {"expected": True}
