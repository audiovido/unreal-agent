"""FREEBUFF ASSET P1: in-Blender verification battery.

Runs inside Blender (headless):
  blender --background --factory-startup --python blender_p1_battery.py -- <report_json>

Verifies bpy, creates + saves a .blend, exports FBX + GLB with Unreal-ready
settings (reusing blender_agent exporters), renders a proof PNG, and writes a
structured JSON report. Exit code 0 = all checks pass.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import bpy  # noqa: F401  (presence is the first check)

TOOLS_DIR = Path(__file__).resolve().parent
ASSETLIB = TOOLS_DIR.parent
ROOT = ASSETLIB.parent
for _p in (str(ROOT), str(TOOLS_DIR.parent.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def main() -> int:
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    report_path = Path(args[0]) if args else ASSETLIB / "proof" / "blender_p1_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    started = time.time()
    report: dict = {
        "step": "p1_blender_verify",
        "started_at": started,
        "blender": {
            "version": bpy.app.version_string,
            "version_tuple": list(bpy.app.version),
            "build_date": getattr(bpy.app, "build_date", None),
            "build_time": getattr(bpy.app, "build_time", None),
            "python": sys.version.split()[0],
            "bpy_import_ok": True,
        },
        "checks": {},
        "ok": False,
    }

    def fail(reason: str, **extra) -> int:
        report["error"] = reason
        report.update(extra)
        report["elapsed_seconds"] = round(time.time() - started, 1)
        report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(f"BLENDER_BATTERY_FAIL: {reason}", flush=True)
        return 1

    # ---- addons -----------------------------------------------------------
    addons = {}
    try:
        bpy.ops.preferences.addon_enable(module="io_scene_fbx")
        addons["io_scene_fbx"] = True
    except Exception:
        addons["io_scene_fbx"] = False
    try:
        bpy.ops.preferences.addon_enable(module="io_scene_gltf2")
        addons["io_scene_gltf2"] = True
    except Exception:
        addons["io_scene_gltf2"] = False
    report["addons"] = addons
    if not (addons.get("io_scene_fbx") and addons.get("io_scene_gltf2")):
        return fail(f"export addons unavailable: {addons}")
    report["checks"]["addons"] = True

    # ---- scene (metric, multi-object) ------------------------------------
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for coll in list(bpy.data.collections):
        if coll.users == 0:
            bpy.data.collections.remove(coll)

    def _principled(name: str, color, roughness=0.4) -> object:
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Base Color"].default_value = (*color, 1.0)
            bsdf.inputs["Roughness"].default_value = roughness
        return mat

    floor_mat = _principled("P1_FloorMat", (0.16, 0.17, 0.18), 0.9)
    top_mat = _principled("P1_TableMat", (0.8, 0.6, 0.2), 0.25)
    leg_mat = _principled("P1_LegMat", (0.2, 0.2, 0.22), 0.5)
    head_mat = _principled("P1_HeadMat", (0.72, 0.18, 0.18), 0.35)

    def _add(mesh_builder, name: str, loc, scale, mat) -> object:
        mesh_builder()
        obj = bpy.context.active_object
        obj.name = name
        obj.location = loc
        obj.scale = scale
        if obj.data.materials:
            obj.data.materials.clear()
        obj.data.materials.append(mat)
        return obj

    def _uv_smart(obj) -> None:
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        try:
            bpy.ops.uv.smart_project(angle_limit=1.2, island_margin=0.02)
        except Exception:
            pass
        bpy.ops.object.mode_set(mode="OBJECT")

    objs = []
    objs.append(_add(lambda: bpy.ops.mesh.primitive_plane_add(size=1), "P1_Floor", (0, 0, 0), (8, 8, 1), floor_mat))
    objs.append(_add(lambda: bpy.ops.mesh.primitive_cube_add(size=1), "P1_TableTop", (0, 0, 0.85), (1.7, 0.9, 0.06), top_mat))
    objs.append(_add(lambda: bpy.ops.mesh.primitive_cylinder_add(radius=0.035, depth=0.85), "P1_Leg_FL", (-0.72, -0.34, 0.425), (1, 1, 1), leg_mat))
    objs.append(_add(lambda: bpy.ops.mesh.primitive_cylinder_add(radius=0.035, depth=0.85), "P1_Leg_FR", (0.72, -0.34, 0.425), (1, 1, 1), leg_mat))
    objs.append(_add(lambda: bpy.ops.mesh.primitive_cylinder_add(radius=0.035, depth=0.85), "P1_Leg_BL", (-0.72, 0.34, 0.425), (1, 1, 1), leg_mat))
    objs.append(_add(lambda: bpy.ops.mesh.primitive_cylinder_add(radius=0.035, depth=0.85), "P1_Leg_BR", (0.72, 0.34, 0.425), (1, 1, 1), leg_mat))
    objs.append(_add(lambda: bpy.ops.mesh.primitive_monkey_add(size=1), "P1_Monkey", (0, 0, 1.6), (0.34, 0.34, 0.34), head_mat))
    for obj in objs:
        if obj.type == "MESH":
            _uv_smart(obj)
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    report["scene_objects"] = [o.name for o in objs]
    report["checks"]["scene_build"] = len(objs) >= 6

    # ---- save .blend ------------------------------------------------------
    work_dir = ASSETLIB / "tests" / "blender"
    work_dir.mkdir(parents=True, exist_ok=True)
    blend_path = work_dir / "p1_smoke_scene.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    report["blend_file"] = str(blend_path).replace("\\", "/")
    report["blend_size_bytes"] = blend_path.stat().st_size if blend_path.exists() else 0
    report["checks"]["blend_saved"] = blend_path.exists() and blend_path.stat().st_size > 0

    # ---- exports (FBX + GLB) ---------------------------------------------
    from blender_agent.exporters import export_selected_for_unreal

    export_dir = work_dir / "exports"
    exports = []
    for fmt in ("fbx", "glb"):
        try:
            result = export_selected_for_unreal(
                "P1_TableTop", fmt, export_dir,
                job_id="p1_smoke", source="generated:smoke-scene",
                blend_file=str(blend_path),
            )
            exports.append({
                "format": fmt,
                "ok": bool(result.get("ok")),
                "path": result.get("export", {}).get("path"),
                "size_bytes": result.get("export", {}).get("size_bytes"),
                "validation": result.get("validation", {}),
                "error": result.get("error"),
            })
        except Exception as exc:
            exports.append({"format": fmt, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
    report["exports"] = exports
    report["checks"]["exports_fbx_glb"] = all(e.get("ok") for e in exports)

    # ---- proof render -----------------------------------------------------
    bpy.ops.object.select_all(action="DESELECT")
    bounds_min = [min(o.location[i] for o in objs) for i in range(3)]
    bounds_max = [max(o.location[i] for o in objs) for i in range(3)]
    center = [(a + b) / 2.0 for a, b in zip(bounds_min, bounds_max)]
    radius = max(max(b - a for a, b in zip(bounds_min, bounds_max)) * 0.9, 1.5)

    bpy.ops.object.camera_add(location=(center[0], center[1] - radius, center[2] + radius * 0.5))
    camera = bpy.context.active_object
    camera.name = "P1_Proof_Camera"
    scene.camera = camera
    bpy.ops.object.empty_add(type="PLAIN_AXES", location=center)
    empty = bpy.context.active_object
    empty.name = "P1_Target"
    track = camera.constraints.new(type="TRACK_TO")
    track.target = empty
    track.track_axis = "TRACK_NEGATIVE_Z"
    track.up_axis = "UP_Y"

    bpy.ops.object.light_add(type="SUN", location=(center[0], center[1] - radius, center[2] + radius))
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.image_settings.file_format = "PNG"

    render_out = {}
    for engine in ("BLENDER_EEVEE_NEXT", "CYCLES"):
        try:
            scene.render.engine = engine
            if engine == "CYCLES":
                scene.cycles.device = "CPU"
                scene.cycles.samples = 24
            png = ASSETLIB / "proof" / "blender_p1_render.png"
            scene.render.filepath = str(png)
            bpy.ops.render.render(write_still=True)
            if png.exists() and png.stat().st_size > 0:
                render_out = {"engine": engine, "path": str(png).replace("\\", "/"),
                              "size_bytes": png.stat().st_size}
                break
        except Exception:
            continue
    report["render"] = render_out
    report["checks"]["render_proof"] = bool(render_out.get("path"))

    # ---- mesh validation --------------------------------------------------
    mesh_checks = []
    for obj in objs:
        if obj.type != "MESH":
            continue
        mesh_checks.append({
            "name": obj.name,
            "vertices": len(obj.data.vertices),
            "polygons": len(obj.data.polygons),
            "triangles": sum(1 for p in obj.data.polygons if len(p.vertices) == 3) if False else None,
            "has_uv": bool(obj.data.uv_layers),
            "materials": [m.name for m in obj.data.materials if m],
            "bounds_cm": [round(v * 100.0, 2) for v in obj.dimensions],
        })
    report["mesh_validation"] = mesh_checks
    report["checks"]["meshes_valid"] = all(
        m["vertices"] > 0 and m["has_uv"] and m["materials"] for m in mesh_checks
    )

    ok = all(report["checks"].values())
    report["ok"] = bool(ok)
    report["elapsed_seconds"] = round(time.time() - started, 1)
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"BLENDER_BATTERY_DONE ok={ok}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
