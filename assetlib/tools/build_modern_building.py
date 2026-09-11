"""FREEBUFF ASSET: assemble ONE modern building from the CC0 Kenney modular
parts (D:/AI/_Assets/Buildings/ModularBuildings) and export a UE-ready FBX.

Uses the exact validated export kwargs (cm scale, -Z forward, Y up, embedded
textures) from the P2 chain. License: CC0 1.0 (License.txt in-tree).
Usage: blender --background --factory-startup --python build_modern_building.py
"""
import sys
from pathlib import Path

import bpy

KIT = Path(r"D:/AI/_Assets/Buildings/ModularBuildings/Models")
OUT = Path(r"D:/AI/_Assets/Buildings/ModernBuilding/ModernBuilding.fbx")
# 0.625-tall facade modules -> 3 wide x 3 tall slab
PARTS = ["018", "021", "022", "023", "028", "029", "030", "035", "036"]
H = 0.625

for mod in ("io_scene_fbx", "io_scene_gltf2"):
    if mod not in bpy.context.preferences.addons:
        bpy.ops.preferences.addon_enable(module=mod)

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)

imported = []
from mathutils import Matrix
rows, cols = 3, 3
col_w_cache, row_h = {}, []
for i, tag in enumerate(PARTS):
    path = KIT / f"modularBuildings_{tag}.obj"
    bpy.ops.wm.obj_import(filepath=str(path))
    objs = [o for o in bpy.context.selected_objects if o.type == "MESH"]
    for o in objs:
        o.name = f"mb_{tag}"
        zmin = min(v.co.z for v in o.data.vertices)
        o.data.transform(Matrix.Translation((0, 0, -zmin)))
        zext = max(v.co.z for v in o.data.vertices) - min(v.co.z for v in o.data.vertices)
        xext = max(v.co.x for v in o.data.vertices) - min(v.co.x for v in o.data.vertices)
        # measured extents -> parts stack flush regardless of local orientation
        col, row = i % cols, i // rows
        if row >= len(row_h):
            row_h.append(0.0)
        o.location = (col * round(xext, 3), 0.0, row_h[row])
        row_h[row] += zext
        o.select_set(True)
    imported.extend(objs)

if not imported:
    print("NO_PARTS_IMPORTED")
    sys.exit(1)

bpy.context.view_layer.objects.active = imported[0]
bpy.ops.object.join()
bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")
# normalize to meters in Blender -> cm on export (validated contract)
OUT.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.export_scene.fbx(
    filepath=str(OUT),
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
print(f"MODERN_BUILDING_OK {OUT} parts={len(PARTS)}")