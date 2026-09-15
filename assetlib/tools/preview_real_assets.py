"""FREEBUFF ASSET: import + inspect + preview real source assets (in Blender).

Reads a JSON spec (list of {category, model, glb}) passed after ``--``, imports
each GLB into a fresh metric scene, discovers type/skeleton/animations/dims,
renders a preview PNG, and writes per-asset metadata JSON + one aggregate
manifest. Safe content only (source dir carries its own LICENSE files).
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

from blender_agent import importers, screenshots  # noqa: E402


def _anim_names(armature) -> set[str]:
    """All action names bound to an armature (active + NLA strips)."""
    names = set()
    ad = armature.animation_data
    if ad:
        if ad.action:
            names.add(ad.action.name)
        for track in ad.nla_tracks:
            for strip in track.strips:
                if strip.action:
                    names.add(strip.action.name)
    return names


def _reset() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0


def _bounds(objects) -> tuple[list[float], float]:
    meshes = [o for o in objects if o.type == "MESH"]
    if not meshes:
        return [0.0, 0.0, 0.0], 1.0
    mins = [min(o.location[i] - o.dimensions[i] / 2 for o in meshes) for i in range(3)]
    maxs = [max(o.location[i] + o.dimensions[i] / 2 for o in meshes) for i in range(3)]
    size = [round(b - a, 4) for a, b in zip(mins, maxs)]
    center = [(a + b) / 2.0 for a, b in zip(mins, maxs)]
    radius = max(max(size) * 0.75, 0.3)
    return center, radius


def _render(center, radius, out_path: Path, res=(800, 450)) -> bool:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = res[0]
    scene.render.resolution_y = res[1]
    scene.render.image_settings.file_format = "PNG"
    cam_data = bpy.data.cameras.new("PrevCam")
    cam = bpy.data.objects.new("PrevCam", cam_data)
    scene.collection.objects.link(cam)
    cam.location = (center[0], center[1] - radius * 1.6, center[2] + radius * 0.55)
    cam.rotation_euler = (1.25, 0.0, 0.0)
    scene.camera = cam
    sun = bpy.data.lights.new("PrevSun", type="SUN")
    sun.energy = 3.0
    sun_obj = bpy.data.objects.new("PrevSun", sun)
    scene.collection.objects.link(sun_obj)
    sun_obj.rotation_euler = (0.9, 0.2, 0.4)
    scene.render.filepath = str(out_path)
    try:
        bpy.ops.render.render(write_still=True)
    except Exception:
        scene.render.engine = "BLENDER_EEVEE"
        bpy.ops.render.render(write_still=True)
    return out_path.exists() and out_path.stat().st_size > 0


def main(spec_path: str, out_manifest: str) -> int:
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    entries = []
    for item in spec:
        _reset()
        glb = Path(item["glb"])
        imported = importers.import_file(str(glb))
        objs = list(bpy.context.scene.objects)
        meshes = [o for o in objs if o.type == "MESH"]
        armatures = [o for o in objs if o.type == "ARMATURE"]
        anim_names = sorted({name for arm in armatures
                             for name in _anim_names(arm)})
        meshes_list = [o for o in objs if o.type == "MESH"]
        mins = [min(o.location[i] - o.dimensions[i] / 2 for o in meshes_list) for i in range(3)]
        maxs = [max(o.location[i] + o.dimensions[i] / 2 for o in meshes_list) for i in range(3)]
        center, radius = _bounds(objs)
        dims_m = [round(b - a, 4) for a, b in zip(mins, maxs)]
        tris = sum(len(p.vertices) - 2 for m in meshes_list for p in m.data.polygons)

        content_dir = Path(item["content_dir"])
        content_dir.mkdir(parents=True, exist_ok=True)
        preview = content_dir / f"{item['model']}_preview.png"
        ok_render = _render(center, radius, preview)

        entry = {
            "model": item["model"],
            "category": item["category"],
            "glb": str(glb).replace("\\", "/"),
            "import_ok": bool(imported.get("ok")),
            "objects": imported.get("object_count"),
            "meshes": len(meshes_list),
            "triangles": tris,
            "armatures": len(armatures),
            "skeleton": [{"name": a.name, "bones": len(a.data.bones)} for a in armatures],
            "animations": anim_names,
            "dimensions_m": dims_m,
            "materials": sorted({m.name for o in meshes_list for m in o.data.materials if m}),
            "preview": str(preview).replace("\\", "/") if ok_render else None,
            "preview_ok": ok_render,
        }
        entries.append(entry)
        (content_dir / f"{item['model']}_inspect.json").write_text(
            json.dumps(entry, indent=2, default=str), encoding="utf-8")
        print(json.dumps(entry)[:300], flush=True)

    manifest = {"ok": all(e["import_ok"] and e["preview_ok"] for e in entries),
                "entries": entries}
    Path(out_manifest).write_text(json.dumps(manifest, indent=2, default=str),
                                  encoding="utf-8")
    print("PREVIEW_BATTERY_DONE ok=", manifest["ok"], flush=True)
    return 0 if manifest["ok"] else 1


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    sys.exit(main(args[0], args[1]))
