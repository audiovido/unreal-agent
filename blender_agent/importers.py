"""Importers for FBX / GLB / GLTF / OBJ (runs inside headless Blender)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

try:  # pragma: no cover
    import bpy
except Exception:  # pragma: no cover
    bpy = None

from blender_agent.geometry import require_bpy, safe_name

SUPPORTED_IMPORT_EXTENSIONS = {".fbx", ".glb", ".gltf", ".obj"}


def supported_import(source: str) -> bool:
    return Path(str(source)).suffix.lower() in SUPPORTED_IMPORT_EXTENSIONS


def import_file(source: str, name: str | None = None) -> dict[str, Any]:
    """Import an asset file into the scene.

    Returns a descriptor of the imported root objects (meshes + armatures).
    """
    require_bpy()
    path = Path(str(source))
    if not path.exists():
        raise FileNotFoundError(f"source file not found: {path}")
    ext = path.suffix.lower()
    if ext not in SUPPORTED_IMPORT_EXTENSIONS:
        raise ValueError(f"unsupported import format: {ext} (supported: {sorted(SUPPORTED_IMPORT_EXTENSIONS)})")

    bpy.ops.object.select_all(action="DESELECT")
    if ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(path), use_manual_orientation=False)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=str(path))
    else:  # glb / gltf
        bpy.ops.import_scene.gltf(filepath=str(path))

    imported = []
    for obj in bpy.context.selected_objects:
        imported.append({
            "name": obj.name,
            "type": obj.type,
            "parent": obj.parent.name if obj.parent else None,
        })

    if name and imported:
        root = bpy.context.selected_objects[0]
        root.name = safe_name(name)

    return {
        "ok": True,
        "source": str(path).replace("\\", "/"),
        "format": ext.lstrip("."),
        "imported_objects": imported,
        "object_count": len(imported),
    }
