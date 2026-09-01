"""Exporters: FBX / GLB / GLTF with Unreal-ready settings (runs in Blender).

Scale contract for Unreal:
  - Blender scene is metric meters (1 BU = 1 m).
  - FBX export uses apply_unit_scale=True, so Blender writes centimeters —
    Unreal's native unit. A 2 m table imports as 200 Unreal units.
  - glTF/GLB is meter-based by spec; Unreal's glTF importer handles the
    meter->cm conversion on import. A verified Unreal read-back (bounds in cm)
    is the authoritative check; the retry loop adjusts export scale if needed.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

try:  # pragma: no cover
    import bpy
except Exception:  # pragma: no cover
    bpy = None

from blender_agent.geometry import (
    CM_PER_UNIT,
    apply_all_transforms,
    bu_to_cm,
    dimensions_cm,
    mesh_stats,
    require_bpy,
    safe_name,
)

SUPPORTED_EXPORT_FORMATS = {"fbx", "glb", "gltf"}


def _export_path(output_dir: Path, name: str, fmt: str) -> Path:
    ext = ".fbx" if fmt == "fbx" else ".glb" if fmt == "glb" else ".gltf"
    return output_dir / f"{safe_name(name)}{ext}"


def export_fbx(obj_name: str, output_path: Path, *, use_selection: bool = True) -> dict[str, Any]:
    require_bpy()
    obj = bpy.data.objects.get(obj_name)
    if obj is None:
        raise ValueError(f"object not found: {obj_name}")
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        output_path.unlink(missing_ok=True)
    except OSError:
        pass

    bpy.ops.export_scene.fbx(
        filepath=str(output_path),
        use_selection=use_selection,
        apply_unit_scale=True,
        global_scale=1.0,
        apply_scale_options="FBX_SCALE_ALL",
        object_types={"MESH", "ARMATURE", "EMPTY"},
        add_leaf_bones=False,
        bake_anim=bool(obj.animation_data is not None),
        path_mode="COPY",
        embed_textures=True,
        axis_forward="-Z",
        axis_up="Y",
    )
    return _exported_file(output_path, obj_name)


def export_gltf(
    obj_name: str,
    output_path: Path,
    *,
    format: str = "GLB",
) -> dict[str, Any]:
    require_bpy()
    obj = bpy.data.objects.get(obj_name)
    if obj is None:
        raise ValueError(f"object not found: {obj_name}")
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        output_path.unlink(missing_ok=True)
    except OSError:
        pass

    bpy.ops.export_scene.gltf(
        filepath=str(output_path),
        export_format=format,
        use_selection=True,
        export_yup=True,
        export_apply=True,
        export_animations=bool(obj.animation_data is not None),
        export_anim_single_armature=True,
        export_materials="EXPORT",
    )
    return _exported_file(output_path, obj_name)


def _exported_file(output_path: Path, obj_name: str) -> dict[str, Any]:
    if not output_path.exists():
        return {"ok": False, "error": f"export did not create file: {output_path}"}
    return {
        "ok": True,
        "path": str(output_path).replace("\\", "/"),
        "format": output_path.suffix.lower().lstrip("."),
        "size_bytes": output_path.stat().st_size,
        "object": obj_name,
    }


def build_manifest(
    *,
    job_id: str,
    source: str | None,
    blend_file: str | None,
    export: dict[str, Any],
    scale_cm: float | None,
    dimensions: list[float],
    materials: list[dict[str, Any]],
    textures: list[str],
    skeleton: dict[str, Any] | None,
    animations: list[dict[str, Any]],
    validation: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the per-export metadata manifest (Phase 5 spec)."""
    manifest = {
        "job_id": job_id,
        "exported_at": time.time(),
        "source": source,
        "blender_file": blend_file,
        "export_format": (export or {}).get("format"),
        "output_path": (export or {}).get("path"),
        "scale_cm_per_unit": scale_cm if scale_cm is not None else CM_PER_UNIT,
        "dimensions_cm": [round(float(v), 4) for v in dimensions],
        "materials": materials,
        "textures": textures,
        "skeleton": skeleton,
        "animations": animations,
        "validation": validation,
        "unreal_scale_expected": 1.0,
    }
    if extra:
        manifest.update(extra)
    return manifest


def export_selected_for_unreal(
    name: str,
    fmt: str,
    output_dir: Path,
    *,
    job_id: str,
    source: str | None = None,
    blend_file: str | None = None,
) -> dict[str, Any]:
    """Export the named object (with skeleton/anims when present) and produce
    a complete metadata manifest."""
    require_bpy()
    fmt = str(fmt or "fbx").lower()
    if fmt not in SUPPORTED_EXPORT_FORMATS:
        raise ValueError(f"unsupported export format: {fmt} (supported: {sorted(SUPPORTED_EXPORT_FORMATS)})")

    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"object not found: {name}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = _export_path(output_dir, name, fmt)

    if fmt == "fbx":
        export_result = export_fbx(name, out_path)
    else:
        export_result = export_gltf(name, out_path, format="GLB" if fmt == "glb" else "GLTF")

    stats = mesh_stats(obj)
    mat_info = []
    for mat in (obj.data.materials if obj.data else []):
        if mat:
            mat_info.append({
                "name": mat.name,
                "nodes": len(mat.node_tree.nodes) if mat.node_tree else 0,
            })
    textures = []
    for mat in (obj.data.materials if obj.data else []):
        if not mat or not mat.node_tree:
            continue
        for node in mat.node_tree.nodes:
            if node.type == "TEX_IMAGE" and node.image:
                p = node.image.filepath or node.image.name
                if p and str(p) not in textures:
                    textures.append(str(p))

    skel = None
    anims = []
    if obj.type == "ARMATURE":
        skel = {"name": obj.name, "bones": len(obj.data.bones)}
        if obj.animation_data and obj.animation_data.action:
            anims.append({"name": obj.animation_data.action.name, "frames": obj.animation_data.action.frame_range})
    elif obj.parent and obj.parent.type == "ARMATURE":
        arm = obj.parent
        skel = {"name": arm.name, "bones": len(arm.data.bones)}
        if arm.animation_data and arm.animation_data.action:
            anims.append({"name": arm.animation_data.action.name, "frames": arm.animation_data.action.frame_range})

    dimensions = dimensions_cm(obj)
    validation = {
        "ok": bool(export_result.get("ok")),
        "export_file_exists": bool(export_result.get("ok")),
        "object_present": True,
        "dimensions_cm": [round(float(v), 4) for v in dimensions],
        "vertex_count": stats.get("vertex_count", 0),
        "poly_count": stats.get("poly_count", 0),
        "materials": mat_info,
        "skeleton": skel,
        "animations": anims,
    }

    manifest = build_manifest(
        job_id=job_id,
        source=source,
        blend_file=blend_file,
        export=export_result,
        scale_cm=CM_PER_UNIT,
        dimensions=dimensions,
        materials=mat_info,
        textures=textures,
        skeleton=skel,
        animations=anims,
        validation=validation,
        extra={"object_name": name, "export_options": {"apply_unit_scale": True}},
    )
    return {
        "ok": bool(export_result.get("ok")),
        "export": export_result,
        "manifest": manifest,
        "validation": validation,
        "error": None if export_result.get("ok") else export_result.get("error"),
    }
