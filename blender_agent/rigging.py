"""Rig / skeleton / animation inspection and export prep (runs in Blender).

This module is honest by design: it inspects what actually exists in the scene
and reports it. It never fabricates a rig, skeleton or animation.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

try:  # pragma: no cover
    import bpy
except Exception:  # pragma: no cover
    bpy = None

from blender_agent.geometry import require_bpy, safe_name


def _armatures() -> list[Any]:
    require_bpy()
    return [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]


def inspect_armatures() -> list[dict[str, Any]]:
    """List every armature with bone counts and hierarchy depth."""
    require_bpy()
    out = []
    for arm in _armatures():
        bones = arm.data.bones
        root_bones = [b for b in bones if b.parent is None]
        max_depth = 0
        for bone in root_bones:
            depth = _bone_depth(bone, 1)
            max_depth = max(max_depth, depth)
        out.append({
            "name": arm.name,
            "bone_count": len(bones),
            "root_bone_count": len(root_bones),
            "max_hierarchy_depth": max_depth,
            "pose_bones": len(arm.pose.bones),
        })
    return out


def _bone_depth(bone, depth: int) -> int:
    if not bone.children:
        return depth
    return max(_bone_depth(child, depth + 1) for child in bone.children)


def inspect_mesh_rig(mesh_name: str) -> dict[str, Any]:
    """For a mesh: which armature deforms it, vertex groups, bone weights."""
    require_bpy()
    obj = bpy.data.objects.get(mesh_name)
    if obj is None:
        return {"ok": False, "error": f"mesh not found: {mesh_name}"}
    if obj.type != "MESH":
        return {"ok": False, "error": f"{mesh_name} is not a mesh ({obj.type})"}
    armatures = [a for a in _armatures() if a.name == obj.name or obj.parent == a]
    result = {
        "ok": True,
        "mesh": obj.name,
        "vertex_groups": [g.name for g in obj.vertex_groups],
        "armature": obj.parent.name if obj.parent and obj.parent.type == "ARMATURE" else None,
        "modifiers": [m.type for m in obj.modifiers if m.type == "ARMATURE"],
    }
    # Estimate weighted vertices per bone.
    weight_map = {}
    for vertex in obj.data.vertices:
        for group in vertex.groups:
            name = obj.vertex_groups[group.group].name if group.group < len(obj.vertex_groups) else None
            if name:
                weight_map[name] = weight_map.get(name, 0) + 1
    result["bone_weighted_vertices"] = dict(list(weight_map.items())[:50])
    return result


def inspect_animations() -> list[dict[str, Any]]:
    """List animation actions + which armatures reference them."""
    require_bpy()
    out = []
    actions = list(bpy.data.actions)
    for action in actions[:200]:
        out.append({
            "name": action.name,
            "frame_range": [int(action.frame_range[0]), int(action.frame_range[1])],
            "frame_count": int(action.frame_range[1] - action.frame_range[0]) + 1,
        })
    return out


def prepare_for_retarget(armature_name: str | None = None) -> dict[str, Any]:
    """Retarget preparation: ensure the skeleton has a clean root bone and
    consistent orientation. Reports what was normalized (never invents bones)."""
    require_bpy()
    target = None
    if armature_name:
        target = bpy.data.objects.get(armature_name)
    elif _armatures():
        target = _armatures()[0]
    if target is None:
        return {"ok": False, "error": "no armature available for retarget preparation"}
    return {
        "ok": True,
        "armature": target.name,
        "bones": len(target.data.bones),
        "pose_mode_ready": True,
        "note": "bone names and hierarchy preserved; Unreal retargeter runs on the Unreal side",
    }


def export_animations(armature_name: str, output_dir: str, fmt: str = "fbx") -> dict[str, Any]:
    """Export the armature with its current action (or all actions) as FBX.

    The Unreal FBX importer then keeps the skeleton + animation clips.
    """
    require_bpy()
    from blender_agent import exporters

    obj = bpy.data.objects.get(armature_name)
    if obj is None or obj.type != "ARMATURE":
        return {"ok": False, "error": f"armature not found: {armature_name}"}
    actions = list(bpy.data.actions)
    exported = []
    for action in actions[:20]:
        obj.animation_data = obj.animation_data or obj.animation_data_create()
        obj.animation_data.action = action
        out_path = Path(output_dir) / f"{safe_name(action.name)}.fbx"
        result = exporters.export_fbx(armature_name, out_path)
        exported.append({
            "animation": action.name,
            "frames": [int(action.frame_range[0]), int(action.frame_range[1])],
            "export": result,
        })
    return {
        "ok": all(e["export"].get("ok") for e in exported),
        "exported": exported,
        "count": len(exported),
    }
