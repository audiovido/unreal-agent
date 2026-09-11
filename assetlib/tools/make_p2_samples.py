"""FREEBUFF ASSET P2: generate small sample source assets for the contract run.

Creates one FBX, one GLB, one OBJ (cube+cylinder table, monkey, cone) with
materials under assetlib/tests/blender/samples/, exported with the same
Unreal-validated parameters reused elsewhere. Safe, self-made content.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy

TOOLS = Path(__file__).resolve().parent
ASSETLIB = TOOLS.parent
ROOT = ASSETLIB.parent
for _p in (str(ROOT), str(TOOLS.parent.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

SAMPLES = ASSETLIB / "tests" / "blender" / "samples"


def _reset() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.scale_length = 1.0


def _mat(name: str, color) -> None:
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (*color, 1.0)


def _add(op, name: str, mat: str, loc=(0, 0, 0), scale=(1, 1, 1)) -> None:
    op()
    obj = bpy.context.active_object
    obj.name = name
    obj.location = loc
    obj.scale = scale
    obj.data.materials.clear()
    obj.data.materials.append(bpy.data.materials[mat])


def build() -> None:
    SAMPLES.mkdir(parents=True, exist_ok=True)

    # --- table: cube top + 4 cylinder legs (FBX sample) -------------------
    _reset()
    _mat("P2_TableTop", (0.75, 0.55, 0.2))
    _mat("P2_Leg", (0.2, 0.2, 0.22))
    _add(lambda: bpy.ops.mesh.primitive_cube_add(size=1), "P2_TableTop", "P2_TableTop",
         (0, 0, 0.95), (1.2, 0.7, 0.08))
    for (x, y) in ((-0.5, -0.28), (0.5, -0.28), (-0.5, 0.28), (0.5, 0.28)):
        _add(lambda: bpy.ops.mesh.primitive_cylinder_add(radius=0.03, depth=0.9),
             f"P2_Leg_{x}_{y}", "P2_Leg", (x, y, 0.45))
    bpy.ops.export_scene.fbx(
        filepath=str(SAMPLES / "sample_table.fbx"),
        use_selection=False, apply_unit_scale=True, global_scale=1.0,
        apply_scale_options="FBX_SCALE_ALL", object_types={"MESH"},
        add_leaf_bones=False, bake_anim=False, path_mode="COPY",
        embed_textures=True, axis_forward="-Z", axis_up="Y")

    # --- monkey (GLB sample) ----------------------------------------------
    _reset()
    _mat("P2_Monkey", (0.6, 0.15, 0.15))
    _add(lambda: bpy.ops.mesh.primitive_monkey_add(size=1), "P2_Monkey", "P2_Monkey",
         (0, 0, 0), (0.55, 0.55, 0.55))
    bpy.ops.export_scene.gltf(
        filepath=str(SAMPLES / "sample_monkey.glb"),
        export_format="GLB", use_selection=False, export_yup=True,
        export_apply=True, export_animations=False,
        export_anim_single_armature=True, export_materials="EXPORT")

    # --- cone (OBJ sample, .mtl sidecar next to it) -----------------------
    _reset()
    _mat("P2_Cone", (0.2, 0.5, 0.7))
    _add(lambda: bpy.ops.mesh.primitive_cone_add(radius1=0.35, depth=0.9),
         "P2_Cone", "P2_Cone", (0, 0, 0.45))
    bpy.ops.wm.obj_export(
        filepath=str(SAMPLES / "sample_cone.obj"),
        export_selected_objects=False, path_mode="COPY",
        global_scale=1.0, forward_axis="NEGATIVE_Z", up_axis="Y",
        export_materials=True)


if __name__ == "__main__":
    build()
    manifest = {
        "ok": all((SAMPLES / f).exists() for f in
                  ("sample_table.fbx", "sample_monkey.glb", "sample_cone.obj",
                   "sample_cone.mtl")),
        "dir": str(SAMPLES).replace("\\", "/"),
        "files": sorted(p.name for p in SAMPLES.iterdir()),
    }
    (ASSETLIB / "reports").mkdir(parents=True, exist_ok=True)
    (ASSETLIB / "reports" / "milestone_P2_samples.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)
    sys.exit(0 if manifest["ok"] else 1)
