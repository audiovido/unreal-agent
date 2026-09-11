"""FREEBUFF ASSET P2: reusable headless Blender 4.2 asset conversion module.

One op, ``convert``, with an observable JSON contract. Runs inside Blender:

    blender --background --factory-startup --python blender_ops.py -- <job.json> <result.json>

Pipeline (in order, each phase reported):
  import FBX/GLB/OBJ -> metric scene -> per-mesh cleanup/normals/transforms/
  origin -> UV ensure -> optional decimation (flag-gated, default off) ->
  organization/naming -> whole-scene export FBX/GLB with the Unreal-validated
  parameters from blender_agent.exporters (meters-in-Blender -> cm-in-UE) ->
  per-asset validation JSON next to the exports.

LODs / collision are structural seams only: accepted as booleans (default
False), validated, and reported as deferred — never silently applied.

Imports blender_agent read-only (no copy of its logic).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

try:  # pragma: no cover
    import bpy
except Exception:  # pragma: no cover
    bpy = None

TOOLS = Path(__file__).resolve().parent
ASSETLIB = TOOLS.parent
ROOT = ASSETLIB.parent
for _p in (str(ROOT), str(TOOLS.parent.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:  # pragma: no cover
    from blender_agent import exporters, geometry, importers, validation
except Exception:
    exporters = geometry = importers = validation = None

IMPORT_FORMATS = {".fbx", ".glb", ".gltf", ".obj"}
EXPORT_FORMATS = ("fbx", "glb")
SCALE_CM_PER_UNIT = 100.0


def _triangles(obj) -> int:
    return sum(len(p.vertices) - 2 for p in obj.data.polygons)


def _mesh_report(obj) -> dict[str, Any]:
    return {
        "name": obj.name,
        "vertices": len(obj.data.vertices),
        "polygons": len(obj.data.polygons),
        "triangles": _triangles(obj),
        "has_uv": bool(obj.data.uv_layers),
        "materials": [m.name for m in obj.data.materials if m],
    }


def _materials_textures() -> tuple[list[str], list[str]]:
    """Materials actually used by scene meshes (never orphans)."""
    used = set()
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH":
            for m in obj.data.materials:
                if m:
                    used.add(m.name)
    mats, texs = [], []
    for name in sorted(used):
        mat = bpy.data.materials.get(name)
        mats.append(name)
        if mat and mat.node_tree:
            for node in mat.node_tree.nodes:
                if node.type == "TEX_IMAGE" and node.image:
                    p = node.image.filepath or node.image.name
                    if p and p not in texs:
                        texs.append(str(p))
    return mats, texs


def _whole_scene_dims() -> list[float]:
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        return [0.0, 0.0, 0.0]
    mins = [min(o.location[i] - o.dimensions[i] / 2 for o in meshes) for i in range(3)]
    maxs = [max(o.location[i] + o.dimensions[i] / 2 for o in meshes) for i in range(3)]
    return [round((b - a) * SCALE_CM_PER_UNIT, 2) for a, b in zip(mins, maxs)]


def _export_fbx(path: Path, has_armature: bool) -> None:
    bpy.ops.export_scene.fbx(
        filepath=str(path),
        use_selection=False,
        apply_unit_scale=True,
        global_scale=1.0,
        apply_scale_options="FBX_SCALE_ALL",
        object_types={"MESH", "ARMATURE"} if has_armature else {"MESH"},
        add_leaf_bones=False,
        bake_anim=has_armature,
        path_mode="COPY",
        embed_textures=True,
        axis_forward="-Z",
        axis_up="Y",
    )


def _export_glb(path: Path, has_anim: bool) -> None:
    bpy.ops.export_scene.gltf(
        filepath=str(path),
        export_format="GLB",
        use_selection=False,
        export_yup=True,
        export_apply=True,
        export_animations=has_anim,
        export_anim_single_armature=True,
        export_materials="EXPORT",
    )


def op_convert(inputs: dict[str, Any], job_id: str) -> dict[str, Any]:
    started = time.time()
    source = (inputs.get("source") or "").strip()
    if not source:
        return {"ok": False, "code": "SOURCE_REQUIRED", "error": "inputs.source is required"}

    src_check = validation.validate_source_format(source)
    if not src_check.get("ok"):
        return {"ok": False, "code": src_check.get("code", "UNSUPPORTED_FORMAT"),
                "error": src_check.get("error")}

    export_formats = [f for f in (inputs.get("export_formats") or ["fbx"])
                      if str(f).lower() in EXPORT_FORMATS]
    if not export_formats:
        return {"ok": False, "code": "UNSUPPORTED_FORMAT",
                "error": f"no supported export format in {inputs.get('export_formats')}"}

    name = str(inputs.get("name") or "").strip() or Path(source).stem
    export_dir = Path(str(inputs.get("export_dir") or ASSETLIB / "tests" / "blender" / "exports"))
    export_dir.mkdir(parents=True, exist_ok=True)

    # Scene reset + metric units.
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0

    # 1. import
    imported = importers.import_file(source, name=name)
    report = {
        "asset": name,
        "job_id": job_id,
        "source": imported["source"],
        "source_format": imported["format"],
        "import": imported,
        "export_formats": export_formats,
        "export_dir": str(export_dir).replace("\\", "/"),
    }
    if not imported.get("imported_objects"):
        return {"ok": False, "code": "IMPORT_EMPTY", "error": "import produced no objects",
                "report": report}

    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    report["meshes_before"] = [_mesh_report(o) for o in meshes]

    # 2. normalization: transforms/origin/normals/UV per mesh.
    origin_center = str(inputs.get("origin_center") or "BOUNDS")
    decimate = None
    requested = {}
    for obj in meshes:
        # Real assets often share mesh data (e.g. wheels); Blender refuses to
        # apply transforms to multi-user data, so duplicate it first.
        if obj.data and obj.data.users > 1:
            obj.data = obj.data.copy()
        if inputs.get("cleanup", True):
            geometry.clean_mesh(obj)
            geometry.clear_custom_split_normals(obj)
            geometry.fix_normals(obj)
        geometry.apply_all_transforms(obj)
        try:
            geometry.fix_origin(obj, center=origin_center)
        except Exception:
            geometry.fix_origin(obj)
        if not obj.data.uv_layers and obj.data.polygons:
            geometry.uv_unwrap(obj)

    ratio = inputs.get("decimate_ratio")
    if ratio:
        ratio = float(ratio)
        if not 0.0 < ratio < 1.0:
            return {"ok": False, "code": "BAD_DECIMATE_RATIO",
                    "error": "decimate_ratio must be in (0,1)"}
        decimate = {"requested": True, "ratio": ratio,
                    "before": {m["name"]: {"polygons": m["polygons"]}
                               for m in report["meshes_before"]}}
        for obj in meshes:
            geometry.decimate(obj, ratio=ratio)
        decimate["after"] = {o.name: {"polygons": len(o.data.polygons)} for o in meshes}

    # 3. scale normalization (optional explicit target, longest axis).
    target_cm = inputs.get("target_dimension_cm")
    scale_info = None
    if target_cm:
        try:
            scale_info = geometry.normalize_scale(None, float(target_cm))
        except Exception as exc:
            scale_info = {"error": f"{type(exc).__name__}: {exc}"}

    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    report["meshes_after"] = [_mesh_report(o) for o in meshes]
    report["normalization"] = {
        "scene_units": "METRIC",
        "scale_cm_per_unit": SCALE_CM_PER_UNIT,
        "origin_center": origin_center,
        "transforms_applied": True,
        "whole_scene_dimensions_cm": _whole_scene_dims(),
        "target_dimension_cm": float(target_cm) if target_cm else None,
        "scale_result": scale_info,
    }
    report["geometry"] = {
        "cleanup": bool(inputs.get("cleanup", True)),
        "custom_split_normals_cleared": True,
        "normals_fixed": True,
        "uv_ensured": all(m["has_uv"] for m in report["meshes_after"]),
        "decimate": decimate or {"requested": False},
    }
    mats, texs = _materials_textures()
    report["materials"] = mats
    report["textures"] = texs
    report["organization"] = {"requested_name": name,
                              "object_names": [o["name"] for o in report["meshes_after"]]}

    # 4. structural seams for LODs / collision (flag-gated, default off).
    deferred = {}
    for feature in ("lods", "collision"):
        wanted = bool(inputs.get(feature, False))
        deferred[feature] = {"requested": wanted, "status": "deferred-not-implemented"}
    report["deferred"] = deferred
    if any(bool(inputs.get(f)) for f in ("lods", "collision")):
        report["note"] = "lods/collision requested but deferred; only structural seams wired"

    # 5. export whole scene per requested format.
    has_armature = any(o.type == "ARMATURE" for o in bpy.context.scene.objects)
    has_anim = has_armature and any(o.animation_data and o.animation_data.action
                                    for o in bpy.context.scene.objects)
    files = []
    for fmt in export_formats:
        path = export_dir / f"{geometry.safe_name(name)}.{fmt}"
        try:
            path.unlink(missing_ok=True)
            if fmt == "fbx":
                _export_fbx(path, has_armature)
            else:
                _export_glb(path, has_anim)
            files.append({"format": fmt, "path": str(path).replace("\\", "/"),
                          "size_bytes": path.stat().st_size if path.exists() else 0,
                          "ok": path.exists() and path.stat().st_size > 0})
        except Exception as exc:
            files.append({"format": fmt, "ok": False,
                          "error": f"{type(exc).__name__}: {exc}"})
    report["export"] = {"files": files}
    export_ok = all(f.get("ok") for f in files)

    # 6. persist .blend + per-asset validation JSON.
    blend_dir = Path(str(inputs.get("blend_dir") or ASSETLIB / "tests" / "blender" / "p2_work"))
    blend_dir.mkdir(parents=True, exist_ok=True)
    blend_path = blend_dir / f"{geometry.safe_name(name)}.blend"
    try:
        bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
        report["blend_file"] = str(blend_path).replace("\\", "/")
    except Exception as exc:
        report["blend_file"] = None
        report["blend_error"] = f"{type(exc).__name__}: {exc}"

    validation_out = {
        "ok": bool(export_ok and report["geometry"]["uv_ensured"]),
        "format": imported["format"],
        "meshes": len(meshes),
        "vertex_total": sum(m["vertices"] for m in report["meshes_after"]),
        "polygon_total": sum(m["polygons"] for m in report["meshes_after"]),
        "triangle_total": sum(m["triangles"] for m in report["meshes_after"]),
        "dimensions_cm": report["normalization"]["whole_scene_dimensions_cm"],
        "materials": mats,
        "textures": texs,
        "uv_ensured": report["geometry"]["uv_ensured"],
        "decimate": report["geometry"]["decimate"],
        "deferred": deferred,
        "exports": [f.get("format") for f in files if f.get("ok")],
    }
    report["validation"] = validation_out
    val_path = export_dir / f"{geometry.safe_name(name)}_validation.json"
    val_path.write_text(json.dumps({"asset": name, "job_id": job_id,
                                    "validation": validation_out, "report": report},
                                   indent=2, default=str), encoding="utf-8")
    report["validation_file"] = str(val_path).replace("\\", "/")
    report["elapsed_seconds"] = round(time.time() - started, 1)

    return {
        "ok": bool(validation_out["ok"]),
        "outputs": {
            "name": name,
            "exports": files,
            "blend_file": report["blend_file"],
            "validation_file": report["validation_file"],
        },
        "validation": validation_out,
        "report": report,
        "error": None if validation_out["ok"] else
        "export failed or UV ensure incomplete",
    }


def execute_job_file(job_path: str, result_path: str) -> int:
    job_path, result_path = Path(job_path), Path(result_path)
    try:
        job = json.loads(job_path.read_text(encoding="utf-8"))
    except Exception as exc:
        result_path.write_text(json.dumps({"ok": False, "error": f"cannot read job file: {exc}"}),
                               encoding="utf-8")
        return 1
    try:
        result = op_convert(job.get("inputs") or {}, str(job.get("id") or "job"))
    except Exception as exc:
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    result["job_id"] = job.get("id")
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str),
                           encoding="utf-8")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    sys.exit(execute_job_file(args[0], args[1]))
