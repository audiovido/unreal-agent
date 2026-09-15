"""Headless proof screenshots from Blender (Eevee render).

The final proof of record is the Unreal viewport capture; Blender screenshots
are supplementary evidence stored under workspace/assets/proof/.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

try:  # pragma: no cover
    import bpy
except Exception:  # pragma: no cover
    bpy = None

from blender_agent.geometry import require_bpy, safe_name


def setup_scene_camera(name: str) -> dict[str, Any]:
    """Frame the named object with a camera; returns placement evidence."""
    require_bpy()
    obj = bpy.data.objects.get(name)
    if obj is None:
        return {"ok": False, "error": f"object not found: {name}"}

    # Ensure a camera exists.
    camera = bpy.data.objects.get("UA_Proof_Camera")
    if camera is None:
        bpy.ops.object.camera_add(location=(0, -6, 3))
        camera = bpy.context.active_object
        camera.name = "UA_Proof_Camera"
    scene = bpy.context.scene
    scene.camera = camera

    dims = [abs(v) for v in obj.dimensions]
    radius = max(max(dims) * 1.6, 2.0)
    cam_z = dims[2] * 0.6 + 0.8

    target = obj.location
    camera.location = (target.x + 0.0, target.y - radius, target.z + cam_z)
    camera.rotation_euler = (0.9, 0.0, 0.0)

    # Aim helper: use a track-to constraint pointing at the object.
    bpy.ops.object.select_all(action="DESELECT")
    camera.select_set(True)
    bpy.context.view_layer.objects.active = camera
    track = None
    for constraint in camera.constraints:
        if constraint.type == "TRACK_TO":
            track = constraint
    if track is None:
        track = camera.constraints.new(type="TRACK_TO")
        track.track_axis = "TRACK_NEGATIVE_Z"
        track.up_axis = "UP_Y"
    track.target = obj

    return {
        "ok": True,
        "camera": camera.name,
        "target": name,
        "location": [camera.location.x, camera.location.y, camera.location.z],
        "radius": radius,
    }


def render_proof(name: str, output_dir: Path, resolution=(1280, 720)) -> dict[str, Any]:
    """Render the current scene (Eevee) to a PNG proof file."""
    require_bpy()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{safe_name(name)}_proof.png"
    try:
        out_path.unlink(missing_ok=True)
    except OSError:
        pass

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = int(resolution[0])
    scene.render.resolution_y = int(resolution[1])
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(out_path)
    scene.render.film_transparent = False

    try:
        bpy.ops.render.render(write_still=True)
    except Exception as exc:  # EEVEE_NEXT fallback
        scene.render.engine = "BLENDER_EEVEE"
        bpy.ops.render.render(write_still=True)

    exists = out_path.exists()
    return {
        "ok": exists and out_path.stat().st_size > 0,
        "path": str(out_path).replace("\\", "/") if exists else None,
        "size_bytes": out_path.stat().st_size if exists else 0,
        "camera": scene.camera.name if scene.camera else None,
    }
