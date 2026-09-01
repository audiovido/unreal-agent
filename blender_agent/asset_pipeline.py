"""Operation dispatch for headless Blender jobs.

``execute_job_file`` is the entry point invoked by the generated runner script.
Each operation returns a structured result {ok, outputs, validation, manifest,
error} which the runner persists onto the job record.

The character pipeline is honest: when no realistic source character (mesh +
armature) exists it returns REALISTIC_CHARACTER_SOURCE_REQUIRED instead of
fabricating a low-quality result.
"""
from __future__ import annotations

import json
import time
import traceback
from pathlib import Path
from typing import Any

try:  # pragma: no cover
    import bpy
except Exception:  # pragma: no cover
    bpy = None

from blender_agent.config import ensure_workspace, in_blender
from blender_agent import exporters, geometry, importers, materials, rigging, screenshots, validation

REALISTIC_CHARACTER_SOURCE_REQUIRED = "REALISTIC_CHARACTER_SOURCE_REQUIRED"

# All image / texture extensions copied or referenced by the pipeline.
TEXTURE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tga", ".bmp", ".tif", ".tiff", ".exr", ".hdr"}


def _result(
    ok: bool,
    *,
    outputs: dict[str, Any] | None = None,
    validation_out: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
    error: Any = None,
    code: str | None = None,
) -> dict[str, Any]:
    out = {"ok": bool(ok), "outputs": outputs or {}, "validation": validation_out or {}, "manifest": manifest or {}, "error": error}
    if code:
        out["code"] = code
    return out


def _blend_path(job_id: str) -> Path:
    layout = ensure_workspace()
    return layout["blender_work"] / f"{job_id}.blend"


def _export_dir(inputs: dict[str, Any]) -> Path:
    layout = ensure_workspace()
    requested = inputs.get("export_dir") or inputs.get("output_dir")
    if requested:
        return Path(str(requested))
    return layout["exports"]


def _set_scene_units():
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0  # 1 BU = 1 meter


def _root_object_names() -> list[str]:
    return [obj.name for obj in bpy.context.scene.objects if obj.parent is None]


# ============================================================
# OPERATIONS
# ============================================================

def op_create_primitive(inputs: dict[str, Any], job_id: str) -> dict[str, Any]:
    _set_scene_units()
    name = str(inputs.get("name") or "UA_Asset").strip()
    desc = geometry.build_model(inputs)
    obj = bpy.data.objects[desc["name"]]

    geometry.apply_all_transforms(obj)
    geometry.fix_origin(obj, center="BOTTOM")
    geometry.fix_normals(obj)

    expected_dims = inputs.get("expected_dimensions_cm") or inputs.get("dimensions_cm")
    scale_info = geometry.normalize_scale(obj, None)
    if expected_dims:
        target = [float(v) for v in expected_dims]
        current = geometry.dimensions_cm(obj)
        factors = [t / c if c else 1.0 for t, c in zip(target, current)]
        obj.scale = tuple(factors)
        geometry.apply_all_transforms(obj)
        geometry.fix_origin(obj, center="BOTTOM")
        scale_info = {"before_cm": current, "after_cm": geometry.dimensions_cm(obj)}

    mat_inputs = inputs.get("materials") or ["white"]
    if isinstance(mat_inputs, str):
        mat_inputs = [mat_inputs]
    mat_result = materials.apply_materials_to_object(obj.name, mat_inputs)

    fmt = str(inputs.get("export_format") or "fbx").lower()
    out_dir = _export_dir(inputs)
    export = exporters.export_selected_for_unreal(
        obj.name, fmt, out_dir,
        job_id=job_id,
        source=f"generated:{desc.get('shape')}",
        blend_file=str(_blend_path(job_id)),
    )

    bpy.ops.wm.save_as_mainfile(filepath=str(_blend_path(job_id)))
    proof = {}
    if inputs.get("screenshot"):
        screenshots.setup_scene_camera(obj.name)
        proof = screenshots.render_proof(obj.name, ensure_workspace()["proof"])

    validation_out = dict(export.get("validation") or {})
    validation_out.update({
        "scale_info": scale_info,
        "expected_dimensions_cm": [float(v) for v in expected_dims] if expected_dims else None,
        "materials": mat_result,
        "proof": proof,
    })
    dim_check = None
    if expected_dims:
        dim_check = validation.validate_dimensions(geometry.dimensions_cm(obj), expected_dims)
        validation_out["dimension_check"] = dim_check
    validation_out["ok"] = bool(export.get("ok") and (dim_check is None or dim_check.get("ok")))

    return _result(
        export.get("ok"),
        outputs={
            "object_name": obj.name,
            "shape": desc.get("shape"),
            "export": export.get("export"),
            "blend_file": str(_blend_path(job_id)).replace("\\", "/"),
            "proof": proof,
        },
        validation_out=validation_out,
        manifest=export.get("manifest"),
        error=export.get("error"),
    )


def op_convert_asset(inputs: dict[str, Any], job_id: str) -> dict[str, Any]:
    """Import a source file and re-export it (with optional cleanup)."""
    _set_scene_units()
    source = inputs.get("source")
    if not source:
        return _result(False, error="inputs.source is required", code="SOURCE_REQUIRED")
    src_check = validation.validate_source_format(source)
    if not src_check.get("ok"):
        return _result(False, error=src_check.get("error"), code=src_check.get("code"))

    imported = importers.import_file(source)
    name = str(inputs.get("name") or imported["imported_objects"][0]["name"]).strip()

    if inputs.get("cleanup", True):
        for obj in bpy.context.selected_objects:
            if obj.type == "MESH":
                geometry.clean_mesh(obj)
                geometry.fix_normals(obj)
                geometry.apply_all_transforms(obj)
                geometry.fix_origin(obj)

    fmt = str(inputs.get("export_format") or "fbx").lower()
    if fmt not in validation.SUPPORTED_EXPORT_FORMATS:
        return _result(False, error=f"unsupported export format: {fmt}", code="UNSUPPORTED_FORMAT")
    out_dir = _export_dir(inputs)
    export = exporters.export_selected_for_unreal(
        name, fmt, out_dir,
        job_id=job_id,
        source=source,
        blend_file=str(_blend_path(job_id)),
    )
    bpy.ops.wm.save_as_mainfile(filepath=str(_blend_path(job_id)))

    validation_out = dict(export.get("validation") or {})
    validation_out["import"] = imported
    return _result(
        export.get("ok"),
        outputs={
            "object_name": name,
            "import": imported,
            "export": export.get("export"),
            "blend_file": str(_blend_path(job_id)).replace("\\", "/"),
        },
        validation_out=validation_out,
        manifest=export.get("manifest"),
        error=export.get("error"),
    )


def op_prepare_asset(inputs: dict[str, Any], job_id: str) -> dict[str, Any]:
    """Generic mesh/asset preparation: cleanup, transforms, scale, UV, materials."""
    _set_scene_units()
    source = inputs.get("source")
    name = str(inputs.get("name") or "UA_Prepared_Asset").strip()

    if source:
        src_check = validation.validate_source_format(source)
        if not src_check.get("ok"):
            return _result(False, error=src_check.get("error"), code=src_check.get("code"))
        importers.import_file(source, name=name)
    else:
        geometry.build_model({**inputs, "name": name, "shape": inputs.get("shape", "cube")})

    obj = bpy.data.objects.get(name)
    if obj is None and bpy.context.selected_objects:
        obj = bpy.context.selected_objects[0]
        name = obj.name
    if obj is None:
        return _result(False, error=f"no object available named {name}", code="NO_OBJECT")

    if inputs.get("cleanup", True):
        geometry.clean_mesh(obj)
        geometry.fix_normals(obj)
    if inputs.get("clear_custom_normals", True):
        geometry.clear_custom_split_normals(obj)
    geometry.apply_all_transforms(obj)
    geometry.fix_origin(obj, center=inputs.get("origin_center", "BOTTOM"))
    scale_result = geometry.normalize_scale(obj, inputs.get("target_dimension_cm"))
    if inputs.get("uv_unwrap"):
        geometry.uv_unwrap(obj)
    ratio = inputs.get("decimate_ratio")
    target_tris = inputs.get("decimate_target_tris")
    decimated = None
    if ratio or target_tris:
        decimated = {"before": geometry.mesh_stats(obj)}
        geometry.decimate(obj, ratio=float(ratio or 0.5), target_tris=target_tris)
        decimated["after"] = geometry.mesh_stats(obj)

    mat_inputs = inputs.get("materials")
    mat_result = None
    if mat_inputs:
        if isinstance(mat_inputs, str):
            mat_inputs = [mat_inputs]
        mat_result = materials.apply_materials_to_object(obj.name, mat_inputs)
        textures = inputs.get("textures") or {}
        if textures and mat_result.get("materials"):
            for mat_name in mat_result["materials"]:
                materials.assign_textures(mat_name, textures)

    fmt = str(inputs.get("export_format") or "fbx").lower()
    if fmt not in validation.SUPPORTED_EXPORT_FORMATS:
        return _result(False, error=f"unsupported export format: {fmt}", code="UNSUPPORTED_FORMAT")
    out_dir = _export_dir(inputs)
    export = exporters.export_selected_for_unreal(
        obj.name, fmt, out_dir,
        job_id=job_id,
        source=source,
        blend_file=str(_blend_path(job_id)),
    )
    bpy.ops.wm.save_as_mainfile(filepath=str(_blend_path(job_id)))

    validation_out = dict(export.get("validation") or {})
    validation_out.update({
        "cleanup": True,
        "transforms_applied": True,
        "scale": scale_result,
        "decimated": decimated,
        "materials": mat_result,
    })
    return _result(
        export.get("ok"),
        outputs={
            "object_name": obj.name,
            "export": export.get("export"),
            "blend_file": str(_blend_path(job_id)).replace("\\", "/"),
        },
        validation_out=validation_out,
        manifest=export.get("manifest"),
        error=export.get("error"),
    )


def op_prepare_character(inputs: dict[str, Any], job_id: str) -> dict[str, Any]:
    """Character preparation pipeline.

    With a real source character (mesh + armature), prepares an Unreal-ready
    FBX preserving skeleton/animations. Without one, returns
    REALISTIC_CHARACTER_SOURCE_REQUIRED with a precise report — never a fake.
    """
    _set_scene_units()
    source = inputs.get("source")
    name = str(inputs.get("name") or "UA_Character").strip()

    if source:
        src_check = validation.validate_source_format(source)
        if not src_check.get("ok"):
            return _result(False, error=src_check.get("error"), code=src_check.get("code"))
        importers.import_file(source, name=name)

    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    armatures = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]

    report = {
        "source": source,
        "meshes": [{"name": o.name, "vertices": len(o.data.vertices)} for o in meshes],
        "armatures": rigging.inspect_armatures(),
        "animations": rigging.inspect_animations(),
        "materials": [],
        "textures": [],
    }

    character_mesh = None
    for mesh in meshes:
        if mesh.parent and mesh.parent.type == "ARMATURE":
            character_mesh = mesh
            break
    if character_mesh is None and meshes and armatures:
        # Deformation evidence: vertex groups matching bone names.
        for mesh in meshes:
            groups = {g.name for g in mesh.vertex_groups}
            bones = {b.name for b in armatures[0].data.bones}
            if groups & bones:
                character_mesh = mesh
                break

    # A photoreal human cannot be procedurally invented. If no real source
    # mesh+armature exists, report exactly what is missing.
    if character_mesh is None or not armatures:
        missing = []
        if not meshes:
            missing.append("mesh")
        if not armatures:
            missing.append("armature/skeleton")
        return _result(
            False,
            code=REALISTIC_CHARACTER_SOURCE_REQUIRED,
            error=(
                "No realistic character source exists. A photoreal human "
                "cannot be procedurally generated. "
                f"Missing: {', '.join(missing)}. "
                "Provide an FBX/GLB character (mesh + skeleton + animations) "
                "or use the Unreal engine mannequin instead."
            ),
            outputs={"character_source_report": report, "missing": missing},
            validation_out={"ok": False, "report": report, "code": REALISTIC_CHARACTER_SOURCE_REQUIRED},
        )

    target = character_mesh
    geometry.apply_all_transforms(target)
    geometry.fix_origin(target, center="BOTTOM")
    scale_result = geometry.normalize_scale(target, inputs.get("target_height_cm"))
    geometry.clean_mesh(target)
    geometry.fix_normals(target)

    armature = target.parent if target.parent and target.parent.type == "ARMATURE" else armatures[0]
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature

    for obj in bpy.context.selected_objects:
        if obj.type == "MESH":
            geometry.apply_all_transforms(obj)
            geometry.fix_origin(obj)

    mat_inputs = inputs.get("materials")
    if mat_inputs:
        if isinstance(mat_inputs, str):
            mat_inputs = [mat_inputs]
        materials.apply_materials_to_object(target.name, mat_inputs)

    # Preserve animations: keep every action bound; bake to FBX.
    anim_names = [a["name"] for a in rigging.inspect_animations()]

    fmt = str(inputs.get("export_format") or "fbx").lower()
    if fmt not in validation.SUPPORTED_EXPORT_FORMATS:
        return _result(False, error=f"unsupported export format: {fmt}", code="UNSUPPORTED_FORMAT")
    out_dir = _export_dir(inputs)
    export = exporters.export_selected_for_unreal(
        armature.name if armature else target.name, fmt, out_dir,
        job_id=job_id,
        source=source,
        blend_file=str(_blend_path(job_id)),
    )
    bpy.ops.wm.save_as_mainfile(filepath=str(_blend_path(job_id)))

    rig_report = rigging.inspect_mesh_rig(target.name)
    validation_out = dict(export.get("validation") or {})
    validation_out.update({
        "character": True,
        "mesh": target.name,
        "armature": armature.name if armature else None,
        "bone_count": len(armature.data.bones) if armature else 0,
        "animations_preserved": anim_names,
        "scale": scale_result,
        "rig": rig_report,
        "report": report,
    })
    return _result(
        export.get("ok"),
        outputs={
            "object_name": target.name,
            "armature": armature.name if armature else None,
            "export": export.get("export"),
            "blend_file": str(_blend_path(job_id)).replace("\\", "/"),
            "character_report": report,
        },
        validation_out=validation_out,
        manifest=export.get("manifest"),
        error=export.get("error"),
    )


def op_inspect_asset(inputs: dict[str, Any], job_id: str) -> dict[str, Any]:
    """Import (temporarily) and report everything about a source asset."""
    _set_scene_units()
    source = inputs.get("source")
    if not source:
        return _result(False, error="inputs.source is required", code="SOURCE_REQUIRED")
    src_check = validation.validate_source_format(source)
    if not src_check.get("ok"):
        return _result(False, error=src_check.get("error"), code=src_check.get("code"))

    imported = importers.import_file(source)

    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    armatures = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
    report = {
        "source": source,
        "format": src_check.get("ext"),
        "objects": [{"name": o.name, "type": o.type, "parent": o.parent.name if o.parent else None}
                    for o in bpy.context.scene.objects],
        "meshes": [geometry.mesh_stats(o) for o in meshes],
        "armatures": rigging.inspect_armatures(),
        "animations": rigging.inspect_animations(),
        "materials": [],
        "textures": [],
    }
    for mesh in meshes:
        for mat in mesh.data.materials:
            if mat:
                report["materials"].append(mat.name)
                if mat.node_tree:
                    for node in mat.node_tree.nodes:
                        if node.type == "TEX_IMAGE" and node.image:
                            report["textures"].append(node.image.filepath or node.image.name)

    bpy.ops.wm.save_as_mainfile(filepath=str(_blend_path(job_id)))
    return _result(True, outputs={"report": report}, validation_out={"ok": True, "report": report})


def op_render_screenshot(inputs: dict[str, Any], job_id: str) -> dict[str, Any]:
    _set_scene_units()
    name = str(inputs.get("name") or "")
    if name and bpy.data.objects.get(name) is not None:
        screenshots.setup_scene_camera(name)
    else:
        obj = bpy.data.objects.get("UA_Blender_Test_Table")
        if obj is None:
            meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
            if not meshes:
                return _result(False, error="no object to screenshot", code="NO_OBJECT")
            obj = meshes[0]
        name = obj.name
        screenshots.setup_scene_camera(obj.name)
    proof = screenshots.render_proof(name, ensure_workspace()["proof"])
    return _result(
        proof.get("ok"),
        outputs={"proof": proof, "object": name},
        validation_out={"ok": proof.get("ok"), "proof": proof},
        error=None if proof.get("ok") else "screenshot render failed",
    )


OPERATIONS = {
    "create_primitive": op_create_primitive,
    "convert_asset": op_convert_asset,
    "prepare_asset": op_prepare_asset,
    "prepare_character": op_prepare_character,
    "inspect_asset": op_inspect_asset,
    "render_screenshot": op_render_screenshot,
}


# ============================================================
# ENTRY POINTS
# ============================================================

def execute_job(job: dict[str, Any]) -> dict[str, Any]:
    """Execute one job dict (already validated) and return the result dict."""
    if not in_blender():
        return _result(False, error="asset_pipeline must run inside Blender (bpy required)", code="NOT_IN_BLENDER")
    operation = job.get("operation")
    inputs = job.get("inputs") or {}
    handler = OPERATIONS.get(operation)
    if handler is None:
        return _result(False, error=f"unknown operation: {operation}", code="UNKNOWN_OPERATION")
    try:
        return handler(inputs, str(job.get("id") or "job"))
    except Exception as exc:
        return _result(
            False,
            error=f"{type(exc).__name__}: {exc}",
            code=getattr(exc, "code", None) or "OPERATION_FAILED",
        )


def execute_job_file(job_path: str | Path, result_path: str | Path) -> int:
    """Entry called by the generated runner script (inside Blender).

    Loads the persisted job, runs its operation, writes a structured result
    file. Returns process exit code 0 on success, 1 on failure.
    """
    job_path = Path(job_path)
    result_path = Path(result_path)
    job: dict[str, Any] = {}
    try:
        job = json.loads(job_path.read_text(encoding="utf-8"))
    except Exception as exc:
        result_path.write_text(
            json.dumps(_result(False, error=f"cannot read job file: {exc}")), encoding="utf-8"
        )
        return 1

    result = execute_job(job)
    result["job_id"] = job.get("id")
    result["operation"] = job.get("operation")
    result["finished_at"] = time.time()
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return 0 if result.get("ok") else 1
