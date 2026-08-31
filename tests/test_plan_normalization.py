from app.api import normalize_execution_plan

TASK = "Create /Game/AgentGraduation/BP_FinalSelfFixProbe. Add String variable AgentGraduationMarker. Initially set it to WRONG_VALUE. Expected value is EXPECTED_VALUE. Validate it. Delete the probe."


def test_normalizes_executable_steps_and_preserves_parameters():
    plan = normalize_execution_plan(TASK, {"goal": "x", "steps": ["inspect", "prepare", "validate"]})
    steps = plan["steps"]
    # unreal_ping is the intentional bridge health check injected after
    # project resolution so a no-path task proves both project recovery AND a
    # connected editor.
    assert [s["preferred_tool"] for s in steps] == ["inspect_project", "unreal_ping", "create_blueprint", "add_blueprint_variable", "set_blueprint_variable_default", "compile_blueprint", "get_blueprint_variable_default", "capture_unreal_viewport", "delete_asset"]
    create = steps[2]
    assert create["target_resource"] == "/Game/AgentGraduation/BP_FinalSelfFixProbe"
    assert steps[3]["parameters"]["variable_type"] == "String"
    assert steps[0]["preferred_tool"] == "inspect_project"
    assert steps[4]["parameters"]["value"] == "WRONG_VALUE"
    assert steps[6]["expected_result"]["expected"] == "EXPECTED_VALUE"
    assert steps[-1]["disposable"] is True


def test_new_project_flow_includes_light_and_evidence_when_requested():
    task = (
        "Create a new disposable Unreal project named UA_GradLightProbe, open it,"
        "spawn a cube actor named UA_LightProbe_Marker with a light, save the level,"
        "verify it, reopen the map, and capture final proof."
    )
    plan = normalize_execution_plan(task, {})
    tools = [s["preferred_tool"] for s in plan["steps"]]
    assert "create_project" in tools
    spawns = [s for s in plan["steps"] if s["preferred_tool"] == "spawn_actor"]
    light_spawn = next((s for s in spawns if (s.get("parameters") or {}).get("class_name") == "PointLight"), None)
    assert light_spawn is not None, "project flow must spawn the requested light"
    assert "get_actor" in tools
    assert "open_map" in tools
    assert "capture_unreal_viewport" in tools, "project flow must capture requested proof"


def test_new_project_flow_without_proof_does_not_add_evidence():
    task = (
        "Create a new disposable Unreal project named UA_GradNoProof, open it, "
        "spawn a cube actor named UA_NoProof_Marker, and save the level."
    )
    plan = normalize_execution_plan(task, {})
    tools = [s["preferred_tool"] for s in plan["steps"]]
    assert "capture_unreal_viewport" not in tools


def test_long_build_gets_blueprint_widget_camera_steps():
    task = (
        "Create a small polished scene: a visible cube named ProdFloor, "
        "environment lighting, a camera, a Blueprint actor named BP_ProdProbe "
        "with a String variable Status initially set to READY and expected "
        "value READY, a simple UMG widget named WBP_ProdWidget, save the map, "
        "and capture a final viewport screenshot."
    )
    plan = normalize_execution_plan(task, {})
    tools = [s["preferred_tool"] for s in plan["steps"]]
    assert "create_blueprint" in tools
    assert "compile_blueprint" in tools
    assert "create_umg_widget" in tools
    assert "spawn_actor" in tools  # camera + floor
    create_bp = next(s for s in plan["steps"] if s["preferred_tool"] == "create_blueprint")
    assert create_bp["parameters"]["asset_path"].endswith("BP_ProdProbe")
    var_step = next(s for s in plan["steps"] if s["preferred_tool"] == "add_blueprint_variable")
    assert var_step["parameters"]["variable_name"] == "Status"
    validate = next(s for s in plan["steps"] if s["preferred_tool"] == "get_blueprint_variable_default")
    assert validate["expected_result"]["expected"] == "READY"
    widget = next(s for s in plan["steps"] if s["preferred_tool"] == "create_umg_widget")
    assert widget["parameters"]["asset_path"].endswith("WBP_ProdWidget")
    assert "capture_unreal_viewport" in tools


def test_reopen_task_gets_open_map_step():
    task = (
        "Create a cube named ReopenCube, save the level, verify it, close and "
        "reopen the project to confirm the map persists, and capture proof."
    )
    plan = normalize_execution_plan(task, {})
    tools = [s["preferred_tool"] for s in plan["steps"]]
    assert "open_map" in tools
    reopen = next(s for s in plan["steps"] if s["preferred_tool"] == "open_map")
    assert reopen["expected_result"]["expected"] is True
    assert reopen["phase"] == "VALIDATE"


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
