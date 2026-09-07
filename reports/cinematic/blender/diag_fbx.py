import sys, json
import bpy
import mathutils

fbx = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else None

def vec(v):
    return [round(v[0], 3), round(v[1], 3), round(v[2], 3)]

def depsgraph_eval(ob):
    dg = bpy.context.evaluated_depsgraph_get()
    return ob.evaluated_get(dg)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=fbx, use_manual_orientation=False, global_scale=1.0)

out = {"fbx": fbx, "unit_scale": bpy.context.scene.unit_settings.scale_length,
       "objects": []}

for ob in bpy.data.objects:
    entry = {
        "name": ob.name,
        "type": ob.type,
        "location": vec(ob.location),
        "rotation_euler": vec(ob.rotation_euler),
        "parent": ob.parent.name if ob.parent else None,
    }
    if ob.type == "ARMATURE":
        bones = []
        for bone in ob.data.bones:
            if not bone.parent:
                head = bone.head_local
                bones.append({"root_bone": bone.name,
                              "head_local": vec(head),
                              "head_world": vec(ob.matrix_world @ bone.head_local),
                              "tail_world": vec(ob.matrix_world @ bone.tail_local),
                              "parent": None})
        entry["root_bones"] = bones
        entry["armature_location"] = vec(ob.location)
    elif ob.type == "MESH":
        # world-space bounds of the evaluated mesh
        dg = bpy.context.evaluated_depsgraph_get()
        eval_ob = ob.evaluated_get(dg)
        bbox = [eval_ob.matrix_world @ mathutils.Vector(c) for c in ob.bound_box]
        zs = [p.z for p in bbox]
        xs = [p.x for p in bbox]
        ys = [p.y for p in bbox]
        entry["bounds_world"] = {
            "x": [round(min(xs), 3), round(max(xs), 3)],
            "y": [round(min(ys), 3), round(max(ys), 3)],
            "z": [round(min(zs), 3), round(max(zs), 3)],
        }
        mats = []
        for slot in ob.data.materials or []:
            mats.append(slot.name if slot else None)
        entry["material_slots"] = mats
        entry["material_count"] = len(ob.data.materials or [])
    out["objects"].append(entry)

print("__DIAG__" + json.dumps(out))