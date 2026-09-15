"""FREEBUFF ASSET: tint a cached asset near-black and export FBX (Blender headless).

Usage (Blender 4.2 CLI):
  blender --background --factory-startup --python tint_black.py -- <in_fbx> <out_fbx>

Reuses the same validated export kwargs as blender_ops._export_fbx (unit cm,
-Z forward / Y up, embedded textures) so the output is UE-ready like the
original convert chain. This is the "Blender processing only when needed"
leg for the natural-language route (black SUV).
"""
import sys
from pathlib import Path

import bpy

in_path = Path(sys.argv[sys.argv.index("--") + 1])
out_path = Path(sys.argv[sys.argv.index("--") + 2])

# ---- import (same conventions as blender_agent.importers.import_file) ----
bpy.context.scene.unit_settings.system = "METRIC"
for mod in ("io_scene_fbx", "io_scene_gltf2"):
    if mod not in bpy.context.preferences.addons:
        bpy.ops.preferences.addon_enable(module=mod)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
bpy.ops.import_scene.fbx(filepath=str(in_path), use_manual_orientation=False)
for ob in bpy.data.objects:
    ob.select_set(True)

# ---- tint: darken base color of every material (keep albedo textures out) --
tinted = []
for mat in bpy.data.materials:
    if mat.node_tree is None:
        continue
    base = mat.node_tree.nodes.get("Principled BSDF")
    if base is None:
        continue
    # Disconnect albedo texture so the dark base color actually shows.
    for inp in ("Base Color", "Base Color (UV)"):
        if inp in base.inputs:
            for link in list(mat.node_tree.links):
                if link.to_socket.name == inp:
                    mat.node_tree.links.remove(link)
    try:
        base.inputs["Base Color"].default_value = (0.015, 0.015, 0.018, 1.0)
    except TypeError:
        base.inputs["Color"].default_value = (0.015, 0.015, 0.018, 1.0)
    tinted.append(mat.name)
print(f"TINTED {len(tinted)} materials: {tinted}", flush=True)

out_path.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.export_scene.fbx(
    filepath=str(out_path),
    use_selection=False,
    apply_unit_scale=True,
    global_scale=1.0,
    apply_scale_options="FBX_SCALE_ALL",
    object_types={"MESH"},
    add_leaf_bones=False,
    bake_anim=False,
    path_mode="COPY",
    embed_textures=True,
    axis_forward="-Z",
    axis_up="Y",
)
print(f"TINT_EXPORT_OK {out_path}", flush=True)