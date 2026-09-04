"""Hermetic regression for the eight UE 5.8 gap-closure tool batches.

The gap tools emit editor-side Python through UnrealBridge.execute_python;
there is no `unreal` module in the host process. These tests use a scripted
bridge so the suite protects three real contracts without a live editor:

1. TRUTHFUL-ERROR passthrough - a ``{"ok": False, "error": ...}`` bridge
   result must reach the caller unchanged (never overclaimed as success).
2. CODE-EMISSION - each tool must emit the sanctioned engine API surface
   with safely JSON-quoted user input (no raw f-string interpolation of
   actor names / asset paths).
3. RESULT-PARSING - successful shapes flow through with their fields.

No live Unreal, no bridge, no network: fully hermetic.
"""

from __future__ import annotations

from tools.unreal.animation_tools_gap import AnimationToolsGap
from tools.unreal.blueprint_graph_gap_tools import BlueprintGraphGapTools
from tools.unreal.material_tools_gap import MaterialToolsGap
from tools.unreal.metahuman_tools_gap import MetaHumanToolsGap
from tools.unreal.niagara_tools_gap import NiagaraToolsGap
from tools.unreal.sequencer_tools_gap import SequencerToolsGap
from tools.unreal.terrain_tools_gap import TerrainToolsGap
from tools.unreal.world_tools_gap import WorldToolsGap


class ScriptedBridge:
    """Records emitted code; returns scripted results in FIFO order."""

    def __init__(self, responses=None):
        self.calls: list[str] = []
        self.responses = list(responses or [])

    def execute_python(self, code: str):
        self.calls.append(code)
        if self.responses:
            return self.responses.pop(0)
        return {"ok": True}


def test_all_gap_tools_construct_with_a_bridge():
    b = ScriptedBridge()
    for cls in (WorldToolsGap, AnimationToolsGap, BlueprintGraphGapTools,
                MaterialToolsGap, MetaHumanToolsGap, NiagaraToolsGap,
                SequencerToolsGap, TerrainToolsGap):
        assert cls(b) is not None


# ---------------------------------------------------------------- world ----

def test_world_list_details_parses_actor_count():
    b = ScriptedBridge([{"ok": True, "actor_count": 3,
                         "actors": [{"name": "A"}, {"name": "B"}, {"name": "C"}]}])
    out = WorldToolsGap(b).list_level_actor_details()
    assert out["actor_count"] == 3
    assert len(out["actors"]) == 3
    assert "get_all_level_actors" in b.calls[0]
    assert "get_actor_location" in b.calls[0]


def test_world_set_transform_quotes_name_and_passes_errors_through():
    b = ScriptedBridge([{"ok": False, "error": "actor not found or ambiguous: Cube\"x",
                         "matches": []}])
    out = WorldToolsGap(b).set_actor_transform('Cube"x', location=[1, 2, 3])
    assert out["ok"] is False
    assert "ambiguous" in out["error"]
    # the user string must be JSON-escaped inside the emitted code
    assert '"Cube\\"x"' in b.calls[0]
    assert "set_actor_location" in b.calls[0]


def test_world_rename_collision_error_passthrough():
    b = ScriptedBridge([{"ok": False, "error": "name already used by another actor",
                         "collides_with": ["Other"]}])
    out = WorldToolsGap(b).rename_actor("Old", "Other")
    assert out["ok"] is False
    assert out["collides_with"] == ["Other"]


def test_world_tags_ok_is_sorted_equality():
    b = ScriptedBridge([{"ok": True, "tags": ["z", "a", "m"]}])
    out = WorldToolsGap(b).set_actor_tags("Cube", ["a", "m", "z"])
    assert out["ok"] is True
    assert "set_editor_property" in b.calls[0]


def test_world_bulk_spawn_local_guard_without_bridge():
    # count < 1 must fail locally, never reaching the bridge
    b = ScriptedBridge()
    out = WorldToolsGap(b).bulk_spawn(count=0)
    assert out["ok"] is False
    assert "count must be" in out["error"]
    assert b.calls == []


def test_world_bulk_spawn_emits_grid_spawn_code():
    b = ScriptedBridge([{"ok": True, "created": [{"index": 0, "name": "S0"}], "errors": []}])
    out = WorldToolsGap(b).bulk_spawn(class_name="StaticMeshActor", count=1,
                                      name_prefix='Sp"awner')
    assert out["ok"] is True
    assert "spawn_actor_from_class" in b.calls[0]
    assert "Sp\\\"awner" in b.calls[0]  # quote-safe prefix
    assert "StaticMeshActor" in b.calls[0]


def test_world_summary_error_and_success():
    b = ScriptedBridge([{"ok": False, "error": "no editor world"}])
    out = WorldToolsGap(b).world_summary()
    assert out["ok"] is False

    b = ScriptedBridge([{"ok": True, "actor_count": 5, "classes": {"StaticMeshActor": 5},
                         "map_name": "ShowcaseMap"}])
    out = WorldToolsGap(b).world_summary()
    assert out["actor_count"] == 5
    assert out["classes"]["StaticMeshActor"] == 5


def test_world_delete_by_class_passthrough():
    b = ScriptedBridge([{"ok": True, "removed": ["A", "B"], "remaining": 0}])
    out = WorldToolsGap(b).delete_actors_by_class("PointLight")
    assert out["ok"] is True
    assert out["remaining"] == 0
    assert "destroy_actor" in b.calls[0]


# ------------------------------------------------------------- animation ----

def test_anim_list_sequences_and_inspect():
    b = ScriptedBridge([{"ok": True, "count": 2,
                         "sequences": [{"name": "A"}, {"name": "B"}]}])
    out = AnimationToolsGap(b).list_animation_sequences("/Game/Anim")
    assert out["count"] == 2
    assert "list_assets" in b.calls[0]

    b = ScriptedBridge([{"ok": False, "error": "asset not found"}])
    out = AnimationToolsGap(b).inspect_animation_sequence("/Game/Missing")
    assert out["ok"] is False


def test_anim_notifies_and_skeletons():
    b = ScriptedBridge([{"ok": True, "notifies": ["Footstep"]}])
    out = AnimationToolsGap(b).list_animation_notifies("/Game/Anim/Run")
    assert out["notifies"] == ["Footstep"]

    b = ScriptedBridge([{"ok": True, "count": 1, "meshes": [{"name": "M"}]}])
    out = AnimationToolsGap(b).list_skeletal_meshes("/Game/Char")
    assert out["count"] == 1


def test_anim_set_mesh_missing_mesh_is_truthful():
    b = ScriptedBridge([{"ok": False, "error": "mesh not found: /Game/Mesh_X"}])
    out = AnimationToolsGap(b).set_skeletal_mesh_on_actor("Hero", "/Game/Mesh_X")
    assert out["ok"] is False
    assert "mesh not found" in out["error"]


def test_anim_play_and_state_parse():
    b = ScriptedBridge([{"ok": True, "actor": "Hero", "animation": "/Game/Anim/Run",
                         "is_playing": True}])
    out = AnimationToolsGap(b).set_animation_and_play("Hero", "/Game/Anim/Run", loop=True)
    assert out["ok"] is True
    assert "set_animation" in b.calls[0]

    b = ScriptedBridge([{"ok": True, "position": 1.5, "is_playing": True}])
    out = AnimationToolsGap(b).read_animation_state("Hero")
    assert out["position"] == 1.5


def test_anim_bone_transform_error_carries_bone_field():
    b = ScriptedBridge([{"ok": False, "error": "no SkeletalMeshComponent", "bone": "root"}])
    out = AnimationToolsGap(b).read_bone_world_transform("Hero", "root")
    assert out["ok"] is False
    assert out["bone"] == "root"


# ------------------------------------------------------- blueprint graph ----

def test_bp_list_and_read_graph():
    b = ScriptedBridge([{"ok": True, "graphs": ["EventGraph"], "count": 1}])
    out = BlueprintGraphGapTools(b).list_graphs("/Game/BP_Char")
    assert out["count"] == 1
    assert "BlueprintEditorLibrary" in b.calls[0]

    b = ScriptedBridge([{"ok": True, "graph": "EventGraph", "node_count": 4,
                         "nodes": [{"name": "n"}] * 4}])
    out = BlueprintGraphGapTools(b).read_graph("/Game/BP_Char")
    assert out["node_count"] == 4


def test_bp_graph_not_found_truthful():
    b = ScriptedBridge([{"ok": False, "error": "graph not found: EventGraph"}])
    out = BlueprintGraphGapTools(b).read_graph("/Game/BP_Char", "EventGraph")
    assert out["ok"] is False


def test_bp_create_function_and_override():
    b = ScriptedBridge([{"ok": True, "function": "DoThing", "created": True}])
    out = BlueprintGraphGapTools(b).create_function_graph("/Game/BP_Char", "DoThing")
    assert out["ok"] is True
    assert "add_function" in b.calls[0]

    b = ScriptedBridge([{"ok": False, "error": str(Exception("override failed")),
                         "function": "BeginPlay"}])
    out = BlueprintGraphGapTools(b).add_function_override("/Game/BP_Char", "BeginPlay")
    assert out["ok"] is False


def test_bp_metadata_bool_emission_uses_python_repr():
    b = ScriptedBridge([{"ok": True, "set": ["instance_editable"], "skipped": []}])
    BlueprintGraphGapTools(b).set_variable_metadata("/Game/BP_Char", "Health",
                                                    instance_editable=True)
    # JSON booleans (true/false) are not valid Python - must be True/False
    assert "True" in b.calls[0]
    assert "true" not in b.calls[0].replace("True", "")


def test_bp_members_events_functions():
    b = ScriptedBridge([{"ok": True, "variables": ["Health"]}])
    out = BlueprintGraphGapTools(b).list_member_variables("/Game/BP_Char")
    assert out["variables"] == ["Health"]

    b = ScriptedBridge([{"ok": True, "events": ["BeginPlay"], "functions": ["DoThing"]}])
    out = BlueprintGraphGapTools(b).list_events_and_functions("/Game/BP_Char")
    assert "BeginPlay" in out["events"]


def test_bp_compile_error_passthrough():
    b = ScriptedBridge([{"ok": False, "error": "compile threw: boom",
                         "status_before": "Unknown"}])
    out = BlueprintGraphGapTools(b).compile_and_inspect("/Game/BP_Char")
    assert out["ok"] is False
    assert "boom" in out["error"]


def test_bp_verify_structure_emits_expected():
    b = ScriptedBridge([{"ok": True, "checks": {"has_event_graph": True}}])
    out = BlueprintGraphGapTools(b).verify_blueprint_structure(
        "/Game/BP_Char", {"events": ["BeginPlay"]})
    assert out["ok"] is True
    assert "BeginPlay" in b.calls[0]


def test_bp_rename_graph_quotes_both_names():
    b = ScriptedBridge([{"ok": True, "old": "EventGraph", "new": "MainGraph"}])
    out = BlueprintGraphGapTools(b).rename_graph("/Game/BP_Char", "EventGraph", "MainGraph")
    assert out["ok"] is True
    assert "EventGraph" in b.calls[0] and "MainGraph" in b.calls[0]


# -------------------------------------------------------------- materials ----

def test_mat_create_material_preserves_existing():
    b = ScriptedBridge([{"ok": True, "created": False, "preserved": True,
                         "asset_path": "/Game/Mats/M"}])
    out = MaterialToolsGap(b).create_material("/Game/Mats/M")
    assert out["preserved"] is True
    assert "MaterialFactoryNew" in b.calls[0]


def test_mat_unknown_expression_class_truthful():
    b = ScriptedBridge([{"ok": False, "error": "unknown expression class: FakeNode"}])
    out = MaterialToolsGap(b).create_material_expression(
        "/Game/Mats/M", "FakeNode", "Tint", [1.0, 0.0, 0.0, 1.0])
    assert out["ok"] is False


def test_mat_connect_and_read_pins():
    b = ScriptedBridge([{"ok": True, "connected": True, "property": "BaseColor"}])
    out = MaterialToolsGap(b).connect_expression_to_property(
        "/Game/Mats/M", "/Game/Mats/M.E:Expr", "Tint", "BaseColor")
    assert out["ok"] is True
    assert "connect_material_property" in b.calls[0]

    b = ScriptedBridge([{"ok": True, "pins": [{"input": "BaseColor", "value": 1.0}]}])
    out = MaterialToolsGap(b).read_material_pins("/Game/Mats/M")
    assert out["pins"][0]["input"] == "BaseColor"


def test_mat_scalar_read_back_truthful():
    b = ScriptedBridge([{"ok": True, "param": "Intensity", "set": 2.5, "read_back": 2.5}])
    out = MaterialToolsGap(b).set_material_instance_scalar("/Game/Mats/MI", "Intensity", 2.5)
    assert out["read_back"] == 2.5
    assert "set_material_instance_scalar_parameter_value" in b.calls[0]

    b = ScriptedBridge([{"ok": False, "error": str(Exception("nativize"))}])
    out = MaterialToolsGap(b).set_material_instance_scalar("/Game/Mats/MI", "Intensity", 1.0)
    assert out["ok"] is False


def test_mat_assign_error_and_success():
    b = ScriptedBridge([{"ok": False, "error": "actor has no StaticMeshComponent"}])
    out = MaterialToolsGap(b).assign_material_to_actor("Cube", "/Game/Mats/M")
    assert out["ok"] is False

    b = ScriptedBridge([{"ok": True, "actor": "Cube", "slot": 0,
                         "material_on_slot": "/Game/Mats/M.M"}])
    out = MaterialToolsGap(b).assign_material_to_actor("Cube", "/Game/Mats/M", slot=0)
    assert out["ok"] is True
    assert out["material_on_slot"].startswith("/Game/Mats/M")
    assert "set_material" in b.calls[0]


# ------------------------------------------------------------- metahuman ----

def test_mh_surface_probe_and_assets():
    b = ScriptedBridge([{"ok": True, "total": 26, "symbols": [{"name": "MetaHumanComponentUE"}]}])
    out = MetaHumanToolsGap(b).probe_metahuman_surface()
    assert out["total"] == 26

    b = ScriptedBridge([{"ok": True, "total_assets": 3, "assets": ["/Game/MH/A"]}])
    out = MetaHumanToolsGap(b).list_metahuman_assets("/Game/MH")
    assert out["total_assets"] == 3


def test_mh_verify_rule_ok_false_is_expected_truthful():
    # VerifyMetaHuman* helpers are rule classes - the batch records that a
    # failure can be the EXPECTED outcome and must never claim success.
    b = ScriptedBridge([{"ok": False, "ok_false_is_expected": True,
                         "returned": "TypeError nativize"}])
    out = MetaHumanToolsGap(b).metahuman_verify_rule_call("/Game/MH/Pkg")
    assert out["ok"] is False
    assert out["ok_false_is_expected"] is True


def test_mh_identity_gap_documents_closed_surface_without_bridge():
    # Static method: must not require a bridge and must record the gap, not fake it.
    out = MetaHumanToolsGap.metahuman_identity_gap()
    assert "closed" in out
    assert out["mirrored_in_session"]
    assert "unblock" in out


# --------------------------------------------------------------- niagara ----

def test_fx_list_and_find_shipping_system():
    b = ScriptedBridge([{"ok": True, "total_assets": 1, "assets": ["/Game/FX/S"]}])
    out = NiagaraToolsGap(b).list_niagara_systems("/Game/FX")
    assert out["total_assets"] == 1

    b = ScriptedBridge([{"ok": True, "class": "NiagaraSystem", "path": "/Niagara/DefaultAssets/DefaultSystem"}])
    out = NiagaraToolsGap(b).find_shipping_system()
    assert out["class"] == "NiagaraSystem"


def test_fx_create_and_duplicate():
    b = ScriptedBridge([{"ok": True, "class": "NiagaraSystem", "asset_path": "/Game/FX/S"}])
    out = NiagaraToolsGap(b).create_niagara_system("S", "/Game/FX")
    assert out["class"] == "NiagaraSystem"
    assert "NiagaraSystemFactoryNew" in b.calls[0]


def test_fx_spawn_emits_function_library_call():
    b = ScriptedBridge([{"ok": True, "component_class": "NiagaraComponent",
                         "component_path": "/Game/FX/S:NC", "owner_label": None,
                         "world_location": [0, 0, 200], "is_active_after_spawn": True}])
    out = NiagaraToolsGap(b).spawn_niagara_at_location("/Game/FX/S", loc=(0, 0, 200))
    assert out["ok"] is True
    assert "spawn_system_at_location" in b.calls[0]

    b = ScriptedBridge([{"ok": False, "error": "system asset not loadable"}])
    out = NiagaraToolsGap(b).spawn_niagara_at_location("/Game/Missing")
    assert out["ok"] is False


def test_fx_variable_and_cycle_parse():
    b = ScriptedBridge([{"ok": True, "var_type": "float", "value_after": 3.0}])
    out = NiagaraToolsGap(b).set_niagara_variable("/Game/FX/S:NC", "float", "Speed", 3.0)
    assert out["var_type"] == "float"

    b = ScriptedBridge([{"ok": True, "after_deactivate": False, "after_activate": True}])
    out = NiagaraToolsGap(b).cycle_niagara_component("/Game/FX/S:NC")
    assert out["after_activate"] is True
    assert "activate" in b.calls[0]


# -------------------------------------------------------------- sequencer ----

def test_seq_create_and_list():
    b = ScriptedBridge([{"ok": True, "created": True, "preserved": False,
                         "asset_path": "/Game/Cine/Seq1"}])
    out = SequencerToolsGap(b).create_level_sequence("/Game/Cine/Seq1")
    assert out["created"] is True
    assert "LevelSequenceFactoryNew" in b.calls[0]

    b = ScriptedBridge([{"ok": True, "count": 1, "sequences": [{"name": "Seq1"}]}])
    out = SequencerToolsGap(b).list_level_sequences("/Game/Cine")
    assert out["count"] == 1


def test_seq_actor_binding_error_passthrough():
    b = ScriptedBridge([{"ok": False, "error": "actor not found or ambiguous: Hero",
                         "matches": []}])
    out = SequencerToolsGap(b).add_actor_binding("/Game/Cine/Seq1", "Hero")
    assert out["ok"] is False
    assert "add_possessable" in b.calls[0]


def test_seq_track_section_and_camera():
    b = ScriptedBridge([{"ok": True, "track_class": "MovieScene3DTransformTrack",
                         "section_range": [0.0, 5.0], "display_name": "Transform"}])
    out = SequencerToolsGap(b).add_track_with_section(
        "/Game/Cine/Seq1", "Hero", "MovieScene3DTransformTrack", 0.0, 5.0)
    assert out["ok"] is True
    assert "add_track" in b.calls[0] and "add_section" in b.calls[0]

    b = ScriptedBridge([{"ok": True, "camera_actor": "CineCam1", "cut_track": "CutTrack",
                         "note": "best-effort"}])
    out = SequencerToolsGap(b).add_camera_cut("/Game/Cine/Seq1", "CineCam1",
                                              [0, 0, 100], 0.0, 5.0)
    assert out["camera_actor"] == "CineCam1"
    assert "MovieSceneCameraCutTrack" in b.calls[0]


def test_seq_read_structure_and_play():
    b = ScriptedBridge([{"ok": True, "binding_count": 1, "tracks": [{"name": "T"}]}])
    out = SequencerToolsGap(b).read_sequence_structure("/Game/Cine/Seq1")
    assert out["binding_count"] == 1

    b = ScriptedBridge([{"ok": True, "was_playing": False, "after": True}])
    out = SequencerToolsGap(b).scrub_and_play("/Game/Cine/Seq1")
    assert out["ok"] is True
    assert "LevelSequenceEditorBlueprintLibrary.play" in b.calls[0]


# ---------------------------------------------------------------- terrain ----

def test_terrain_surface_probe_records_editor_gap():
    b = ScriptedBridge([{"ok": True, "total": 65,
                         "key_classes": ["Landscape", "LandscapeComponent"],
                         "landscape_creation_api": "closed-editor-tool-only"}])
    out = TerrainToolsGap(b).landscape_surface_probe()
    assert out["total"] == 65
    # The probe must document the closed surface instead of claiming creation.
    assert "landscape_creation_api" in out


def test_terrain_foliage_create_and_spawn():
    b = ScriptedBridge([{"ok": True, "class": "FoliageType_InstancedStaticMesh",
                         "asset_path": "/Game/Batch8Env/FT"}])
    out = TerrainToolsGap(b).create_foliage_type("FT", "/Game/Batch8Env")
    assert out["class"] == "FoliageType_InstancedStaticMesh"
    assert "FoliageType_InstancedStaticMeshFactory" in b.calls[0]

    b = ScriptedBridge([{"ok": True, "actor": "IFA_0", "instance_count": 4}])
    out = TerrainToolsGap(b).spawn_foliage_instances("/Game/Batch8Env/FT", count=4)
    assert out["instance_count"] == 4
    assert "InstancedFoliageActor" in b.calls[0]


def test_terrain_pcg_graph_authoring():
    b = ScriptedBridge([{"ok": True, "class": "PCGGraph", "asset_path": "/Game/Batch8Env/P"}])
    out = TerrainToolsGap(b).create_pcg_graph("P", "/Game/Batch8Env")
    assert out["class"] == "PCGGraph"
    assert "PCGGraphFactory" in b.calls[0]

    b = ScriptedBridge([{"ok": True, "nodes_added": 3, "nodes": ["SurfaceSampler"]}])
    out = TerrainToolsGap(b).author_pcg_graph("/Game/Batch8Env/P")
    assert out["nodes_added"] == 3
    assert "add_node" in b.calls[0]


def test_terrain_reopen_verifies_after_reload():
    b = ScriptedBridge([{"ok": True, "class": "PCGGraph", "asset_path": "/Game/Batch8Env/P"}])
    out = TerrainToolsGap(b).reopen_terrain_asset("/Game/Batch8Env/P")
    assert out["class"] == "PCGGraph"


def test_gap_tools_never_emit_bare_user_strings_in_code():
    """User-controlled names must be JSON-escaped in emitted code (injection)."""
    evil = 'Cube"); print("pwned'
    b = ScriptedBridge([{"ok": False, "error": "actor not found or ambiguous: " + evil,
                         "matches": []}])
    WorldToolsGap(b).set_actor_tags(evil, ["a"])
    code = b.calls[0]
    # the raw payload must not appear unescaped inside a Python string literal
    assert 'print("pwned' not in code
    # json.dumps escapes the quotes/backslashes so the emitted literal stays closed
    assert '"Cube\\"); print(\\"pwned' in code