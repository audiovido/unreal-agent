"""Material creation and texture assignment (runs inside headless Blender).

Pure helpers (color parsing, material specs) are testable outside Blender;
bpy-touching functions require running inside Blender.
"""
from __future__ import annotations

import re
from typing import Any

try:  # pragma: no cover
    import bpy
except Exception:  # pragma: no cover
    bpy = None

from blender_agent.geometry import require_bpy, safe_name

# Material presets usable by any job without texture files.
PRESET_COLORS = {
    "wood": (0.45, 0.30, 0.16),
    "dark_wood": (0.22, 0.14, 0.07),
    "metal": (0.60, 0.60, 0.62),
    "dark_metal": (0.18, 0.18, 0.20),
    "steel": (0.55, 0.58, 0.62),
    "white": (0.85, 0.85, 0.85),
    "black": (0.05, 0.05, 0.05),
    "red": (0.72, 0.12, 0.12),
    "blue": (0.12, 0.24, 0.72),
    "green": (0.12, 0.60, 0.24),
    "orange": (0.85, 0.45, 0.10),
    "gray": (0.50, 0.50, 0.50),
    "concrete": (0.62, 0.60, 0.56),
    "marble": (0.90, 0.88, 0.84),
    "leather": (0.30, 0.16, 0.08),
}

PRESET_METALLIC = {
    "metal": 1.0,
    "dark_metal": 1.0,
    "steel": 1.0,
}

PRESET_ROUGHNESS = {
    "wood": 0.6,
    "dark_wood": 0.7,
    "metal": 0.3,
    "dark_metal": 0.45,
    "steel": 0.25,
    "white": 0.5,
    "black": 0.4,
    "red": 0.5,
    "blue": 0.5,
    "green": 0.5,
    "orange": 0.5,
    "gray": 0.6,
    "concrete": 0.9,
    "marble": 0.25,
    "leather": 0.55,
}


def parse_color(value: Any) -> tuple[float, float, float, float]:
    """Accept preset name, '#rrggbb', 'r,g,b', or a list/tuple of 3 floats."""
    if isinstance(value, (list, tuple)):
        vals = [float(v) for v in value[:3]]
        return (vals[0], vals[1], vals[2], 1.0)
    text = str(value or "").strip().lower()
    if not text:
        return (0.8, 0.8, 0.8, 1.0)
    if text in PRESET_COLORS:
        base = PRESET_COLORS[text]
        return (base[0], base[1], base[2], 1.0)
    if text.startswith("#") and len(text) == 7:
        return (
            int(text[1:3], 16) / 255.0,
            int(text[3:5], 16) / 255.0,
            int(text[5:7], 16) / 255.0,
            1.0,
        )
    match = re.match(r"^([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)$", text)
    if match:
        return (float(match.group(1)), float(match.group(2)), float(match.group(3)), 1.0)
    return (0.8, 0.8, 0.8, 1.0)


def material_spec(material: Any) -> dict[str, Any]:
    """Normalize a material input: dict {name?, color, metallic, roughness} or
    a preset string."""
    if isinstance(material, dict):
        spec = dict(material)
        spec.setdefault("name", safe_name(str(spec.get("name") or "Material")))
        spec["color"] = parse_color(spec.get("color", "white"))
        return spec
    if isinstance(material, str):
        return {
            "name": safe_name(material),
            "color": parse_color(material),
            "metallic": float(PRESET_METALLIC.get(material, 0.0)),
            "roughness": float(PRESET_ROUGHNESS.get(material, 0.6)),
        }
    return {"name": "Material", "color": (0.8, 0.8, 0.8, 1.0), "metallic": 0.0, "roughness": 0.6}


def _base_color_node(material):
    """Find or create the Principled BSDF base color input."""
    node_tree = material.node_tree
    if node_tree is None:
        material.use_nodes = True
        node_tree = material.node_tree
    principled = None
    for node in node_tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            principled = node
            break
    if principled is None:
        principled = node_tree.nodes.new("ShaderNodeBsdfPrincipled")
    return principled


def create_material(spec: dict[str, Any]) -> dict[str, Any]:
    """Create a principled material from a normalized spec dict."""
    require_bpy()
    name = safe_name(str(spec.get("name") or "Material"))
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    principled = _base_color_node(mat)
    r, g, b, a = spec["color"]
    principled.inputs["Base Color"].default_value = (r, g, b, a)
    if "metallic" in spec and "Metallic" in principled.inputs:
        principled.inputs["Metallic"].default_value = float(spec["metallic"])
    if "roughness" in spec and "Roughness" in principled.inputs:
        principled.inputs["Roughness"].default_value = float(spec["roughness"])
    return {"name": mat.name, "created": True}


def assign_material_to_active(name: str) -> dict[str, Any]:
    require_bpy()
    obj = bpy.context.active_object
    if obj is None:
        return {"assigned": False, "error": "no active object"}
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = create_material({"name": name, "color": name})
    if obj.data is not None:
        if obj.data.materials:
            obj.data.materials[0] = mat
        else:
            obj.data.materials.append(mat)
    return {"assigned": True, "object": obj.name, "material": mat.name}


def assign_textures(
    material_name: str,
    textures: dict[str, Any],
) -> dict[str, Any]:
    """Assign texture files to a material's shader inputs.

    textures: {"base_color": "path.png", "normal": "path.png", "roughness": ...}
    Missing files are reported, not fatal.
    """
    require_bpy()
    from pathlib import Path

    mat = bpy.data.materials.get(material_name)
    if mat is None:
        return {"assigned": False, "error": f"material not found: {material_name}"}
    mat.use_nodes = True
    principled = _base_color_node(mat)
    results = {}
    for slot, path in (textures or {}).items():
        p = Path(str(path))
        if not p.exists():
            results[slot] = {"assigned": False, "error": f"texture file missing: {p}"}
            continue
        try:
            image = bpy.data.images.load(str(p))
            tex_node = mat.node_tree.nodes.new("ShaderNodeTexImage")
            tex_node.image = image
            target = None
            slot_lower = str(slot).lower()
            if "color" in slot_lower or "diffuse" in slot_lower or "albedo" in slot_lower:
                target = "Base Color"
            elif "normal" in slot_lower:
                # Link through a Normal Map node.
                norm_node = mat.node_tree.nodes.new("ShaderNodeNormalMap")
                norm_node.inputs["Color"].default_value = (0.5, 0.5, 1.0, 1.0)
                mat.node_tree.links.new(tex_node.outputs["Color"], norm_node.inputs["Color"])
                mat.node_tree.links.new(norm_node.outputs["Normal"], principled.inputs["Normal"])
                results[slot] = {"assigned": True, "texture": str(p)}
                continue
            elif "rough" in slot_lower:
                target = "Roughness"
            elif "metal" in slot_lower:
                target = "Metallic"
            elif "emit" in slot_lower:
                target = "Emission Color"
            if target is not None and target in principled.inputs:
                mat.node_tree.links.new(tex_node.outputs["Color"], principled.inputs[target])
                results[slot] = {"assigned": True, "texture": str(p)}
            else:
                results[slot] = {"assigned": False, "error": f"no shader input for {slot}"}
        except Exception as exc:
            results[slot] = {"assigned": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"assigned": all(v.get("assigned") for v in results.values()), "results": results}


def apply_materials_to_object(object_name: str, materials: list[Any]) -> dict[str, Any]:
    """Create (or reuse) materials and assign them to an object."""
    require_bpy()
    obj = bpy.data.objects.get(object_name)
    if obj is None:
        return {"applied": False, "error": f"object not found: {object_name}"}
    applied = []
    for mat_input in materials or []:
        spec = material_spec(mat_input)
        mat = bpy.data.materials.get(spec["name"])
        if mat is None:
            create_material(spec)
            mat = bpy.data.materials.get(spec["name"])
        if obj.data.materials:
            obj.data.materials[0] = mat
        else:
            obj.data.materials.append(mat)
        applied.append(spec["name"])
    return {"applied": True, "object": obj.name, "materials": applied}
