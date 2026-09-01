"""Geometry operations (runs inside headless Blender via bpy).

Every function takes/returns plain data. Pure helpers (scale math, naming) are
importable outside Blender for deterministic tests; functions touching ``bpy``
fail with a clear message when executed outside Blender.
"""
from __future__ import annotations

from typing import Any

try:  # pragma: no cover - only present inside Blender
    import bpy
except Exception:  # pragma: no cover
    bpy = None

# Unreal works in centimeters. Blender models in meters (1 BU = 1 m) and the
# FBX exporter converts meters -> cm when apply_unit_scale=True.
CM_PER_UNIT = 100.0


def require_bpy():
    if bpy is None:
        raise RuntimeError("geometry requires the bpy module (run inside Blender)")


# ============================================================
# PURE HELPERS (testable outside Blender)
# ============================================================

def cm_to_bu(cm: float) -> float:
    """Convert centimeters to Blender units (meters)."""
    return float(cm) / CM_PER_UNIT


def bu_to_cm(bu: float) -> float:
    return float(bu) * CM_PER_UNIT


def safe_name(name: str, fallback: str = "Object") -> str:
    """Blender-safe object/asset name: ASCII alnum, no dots/spaces issues."""
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in str(name))
    cleaned = cleaned.strip("_")
    return cleaned or fallback


def sanitize_path(value: Any) -> str | None:
    if not value:
        return None
    return str(value)


# ============================================================
# PRIMITIVE CREATION
# ============================================================

PRIMITIVE_SHAPES = {
    "cube": "CUBE",
    "plane": "PLANE",
    "cylinder": "CYLINDER",
    "sphere": "UV_SPHERE",  # Blender >= 2.8x renamed uvsphere -> uv_sphere
    "monkey": "MONKEY",
    "cone": "CONE",
    "torus": "TORUS",
}


def create_primitive(shape: str, name: str) -> dict[str, Any]:
    """Create a base primitive, return its descriptor.

    Version-tolerant operator call: newer Blender (>= 4.x) removed the
    legacy ``size=`` kwargs from several mesh-add operators, so the exact
    kwargs are chosen per primitive with fallbacks (legacy first, then modern
    radius/depth signatures).
    """
    require_bpy()
    shape = str(shape or "cube").lower()
    op = PRIMITIVE_SHAPES.get(shape)
    if op is None:
        raise ValueError(f"unsupported primitive shape: {shape}")
    bpy.ops.object.select_all(action="DESELECT")

    def _call(op_attrs: list[dict]):
        last = None
        for attrs in op_attrs:
            try:
                getattr(bpy.ops.mesh, op_attrs_name)(**attrs)
                return
            except Exception as exc:  # pragma: no cover - API drift guard
                last = exc
        raise last  # type: ignore[misc]

    op_attrs_name = f"primitive_{op.lower()}_add"
    if shape == "cylinder":
        _call([{"size": 1.0}, {"radius": 1.0, "depth": 2.0, "vertices": 32}])
    elif shape == "sphere":
        _call([{"size": 1.0}, {"radius": 1.0, "segments": 32, "ring_count": 16}])
    elif shape == "cone":
        _call([{"size": 1.0}, {"radius1": 1.0, "depth": 2.0}])
    elif shape == "torus":
        _call([{"size": 1.0}, {"major_radius": 1.0, "minor_radius": 0.25, "major_segments": 48, "minor_segments": 12}])
    elif shape == "monkey":
        _call([{"size": 1.0}])
    else:
        try:
            getattr(bpy.ops.mesh, op_attrs_name)(size=1.0)
        except Exception:  # pragma: no cover - API drift guard
            getattr(bpy.ops.mesh, op_attrs_name)(size=2.0)
    obj = bpy.context.active_object
    obj.name = safe_name(name)
    obj.data.name = safe_name(name + "_Mesh")
    return {
        "name": obj.name,
        "shape": shape,
        "type": obj.type,
        "vertex_count": len(obj.data.vertices),
    }


def _build_table(name: str, top_cm, leg_cm, leg_count=4) -> dict[str, Any]:
    """Procedurally build a table: top slab + legs, real dimensions in cm."""
    require_bpy()
    bpy.ops.object.select_all(action="DESELECT")

    top_w, top_d, top_h = top_cm
    leg_h = leg_cm
    # Leg cross-section is derived from the TOP in its own units (cm) then
    # converted to meters — never mix the two.
    leg_w = max(0.04, min(cm_to_bu(top_w), cm_to_bu(top_d)) * 0.08)

    def box(dim_m, loc_m, label):
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=loc_m)
        obj = bpy.context.active_object
        obj.scale = (dim_m[0], dim_m[1], dim_m[2])
        obj.name = safe_name(label)
        obj.data.name = safe_name(label + "_Mesh")
        bpy.ops.object.transform_apply(scale=True)
        return obj

    top_w_m, top_d_m, top_h_m = (cm_to_bu(v) for v in top_cm)
    leg_h_m = cm_to_bu(leg_h)

    box((top_w_m, top_d_m, top_h_m), (0.0, 0.0, leg_h_m + top_h_m / 2.0), name + "_Top")
    legs = []
    for i, (sx, sy) in enumerate(
        ((-1, -1), (-1, 1), (1, -1), (1, 1))[:leg_count]
    ):
        x = sx * (top_w_m / 2.0 - leg_w / 2.0)
        y = sy * (top_d_m / 2.0 - leg_w / 2.0)
        legs.append(box((leg_w, leg_w, leg_h_m), (x, y, leg_h_m / 2.0), f"{name}_Leg{i + 1}"))

    # Join into one mesh named after the table.
    bpy.ops.object.select_all(action="DESELECT")
    for obj in legs + [bpy.data.objects[name + "_Top"]]:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = bpy.data.objects[name + "_Top"]
    bpy.ops.object.join()
    joined = bpy.context.active_object
    joined.name = safe_name(name)
    joined.data.name = safe_name(name + "_Mesh")
    bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")

    return {
        "name": joined.name,
        "shape": "table",
        "type": joined.type,
        "vertex_count": len(joined.data.vertices),
        "poly_count": len(joined.data.polygons),
        "dimensions_cm": dimensions_cm(joined),
    }


def build_model(inputs: dict[str, Any]) -> dict[str, Any]:
    """Create geometry from job inputs.

    Supports:
      - shape-based primitives with optional dimensions + UV sphere resolution
      - procedural "table" (top + legs) used by the live test
    """
    require_bpy()
    shape = str(inputs.get("shape") or "cube").lower()
    name = str(inputs.get("name") or f"UA_{shape}").strip()

    if shape == "table":
        top = inputs.get("top_cm") or inputs.get("dimensions_top_cm") or [200.0, 100.0, 6.0]
        leg = inputs.get("leg_cm") or inputs.get("leg_height_cm") or 74.0
        return _build_table(name, [float(v) for v in top], float(leg))

    desc = create_primitive(shape, name)
    obj = bpy.data.objects[desc["name"]]

    dims_cm = inputs.get("dimensions_cm")
    if dims_cm:
        target = [cm_to_bu(float(v)) for v in dims_cm]
        current = [abs(obj.dimensions[i]) for i in range(3)]
        scale = [target[i] / current[i] if current[i] else 1.0 for i in range(3)]
        obj.scale = (scale[0], scale[1], scale[2])
        bpy.ops.object.transform_apply(scale=True)

    segments = inputs.get("segments")
    if segments and shape == "sphere":
        # Smooth the sphere; cylinder/torus keep their (already dense) base
        # topology rather than spawning a duplicate primitive.
        try:
            bpy.ops.object.modifier_add(type="SUBSURF")
        except Exception:
            pass

    return desc


# ============================================================
# TRANSFORMS / CLEANUP
# ============================================================

def apply_all_transforms(obj=None):
    """Apply location/rotation/scale to the active (or named) object."""
    require_bpy()
    target = obj or bpy.context.active_object
    if target is None:
        return False
    bpy.ops.object.select_all(action="DESELECT")
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return True


def fix_origin(obj=None, center="BOUNDS"):
    """Set origin to geometry bounds (default) — bottom for floor placement."""
    require_bpy()
    target = obj or bpy.context.active_object
    if target is None:
        return False
    bpy.ops.object.select_all(action="DESELECT")
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    if center == "BOTTOM":
        bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")
        # Move origin to the lowest vertex.
        world_z = [target.matrix_world @ v.co for v in target.data.vertices]
        min_z = min(v.z for v in world_z)
        for v in target.data.vertices:
            v.co.z -= min_z
        bpy.ops.object.transform_apply(location=True)
        bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")
    else:
        bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center=center)
    return True


def normalize_scale(obj=None, target_dimension_cm: float | None = None):
    """Scale the object so its largest axis equals target_dimension_cm.

    With no target, just applies transforms (unit cube convention: model at
    real-world size, 1 BU = 1 m). Returns pre/post dimensions in cm.
    """
    require_bpy()
    target = obj or bpy.context.active_object
    if target is None:
        return None
    before = list(target.dimensions)
    if target_dimension_cm:
        largest = max(abs(v) for v in before) or 1.0
        factor = cm_to_bu(float(target_dimension_cm)) / largest
        target.scale = (factor, factor, factor)
        bpy.ops.object.transform_apply(scale=True)
    else:
        bpy.ops.object.transform_apply(scale=True)
    return {"before_cm": [bu_to_cm(v) for v in before], "after_cm": dimensions_cm(target)}


def dimensions_cm(obj=None) -> list[float]:
    require_bpy()
    target = obj or bpy.context.active_object
    if target is None:
        return []
    return [bu_to_cm(abs(v)) for v in target.dimensions]


def mesh_stats(obj=None) -> dict[str, Any]:
    require_bpy()
    target = obj or bpy.context.active_object
    if target is None:
        return {}
    if target.type != "MESH":
        return {"type": target.type, "mesh": False}
    return {
        "mesh": True,
        "name": target.name,
        "vertex_count": len(target.data.vertices),
        "edge_count": len(target.data.edges),
        "poly_count": len(target.data.polygons),
        "materials": len(target.data.materials),
        "dimensions_cm": dimensions_cm(target),
    }


def rename_object(obj, new_name: str) -> str:
    require_bpy()
    obj.name = safe_name(new_name, obj.name)
    if obj.data:
        try:
            obj.data.name = safe_name(new_name + "_Mesh", obj.data.name)
        except Exception:
            pass
    return obj.name


def clean_mesh(obj=None):
    """Remove doubles / degenerate geometry via a remesh-free cleanup."""
    require_bpy()
    target = obj or bpy.context.active_object
    if target is None:
        return False
    bpy.ops.object.select_all(action="DESELECT")
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    if target.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    try:
        bpy.ops.mesh.delete_loose()
    except Exception:
        pass
    try:
        bpy.ops.mesh.dissolve_degenerate()
    except Exception:
        pass
    bpy.ops.mesh.select_all(action="SELECT")
    try:
        bpy.ops.mesh.remove_doubles(threshold=0.0001)
    except Exception:
        pass
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    return True


def fix_normals(obj=None):
    require_bpy()
    target = obj or bpy.context.active_object
    if target is None:
        return False
    bpy.ops.object.select_all(action="DESELECT")
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    return True


def clear_custom_split_normals(obj=None):
    """Remove stale custom normals/tangents before re-export."""
    require_bpy()
    target = obj or bpy.context.active_object
    if target is None:
        return False
    try:
        bpy.ops.mesh.customdata_custom_splitnormals_clear()
    except Exception:
        return False
    return True


def decimate(obj=None, ratio: float = 0.5, target_tris: int | None = None):
    """Collapse geometry with a Decimate modifier; optionally to tri budget."""
    require_bpy()
    target = obj or bpy.context.active_object
    if target is None:
        return False
    mod = target.modifiers.new(name="UA_Decimate", type="DECIMATE")
    if target_tris:
        poly_count = len(target.data.polygons) or 1
        mod.ratio = max(0.01, min(1.0, float(target_tris) / poly_count))
    else:
        mod.ratio = max(0.01, min(1.0, float(ratio)))
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.modifier_apply(modifier=mod.name)
    return True


def generate_lods(name: str, levels: int = 3) -> list[dict[str, Any]]:
    """Generate LOD variants by decimation; returns descriptors."""
    require_bpy()
    src = bpy.data.objects.get(name)
    if src is None:
        return []
    out = []
    ratios = [1.0, 0.5, 0.25][: levels]
    for i, ratio in enumerate(ratios):
        if i == 0:
            out.append({"name": src.name, "lod": 0, "ratio": 1.0, **mesh_stats(src)})
            continue
        dup = src.copy()
        dup.data = src.data.copy()
        bpy.context.collection.objects.link(dup)
        dup.name = safe_name(f"{name}_LOD{i}")
        bpy.ops.object.select_all(action="DESELECT")
        dup.select_set(True)
        bpy.context.view_layer.objects.active = dup
        bpy.ops.object.modifier_add(type="DECIMATE")
        mod = dup.modifiers[-1]
        mod.ratio = ratio
        bpy.ops.object.modifier_apply(modifier=mod.name)
        out.append({"name": dup.name, "lod": i, "ratio": ratio, **mesh_stats(dup)})
    return out


def uv_unwrap(obj=None, margin: float = 0.001):
    require_bpy()
    target = obj or bpy.context.active_object
    if target is None:
        return False
    bpy.ops.object.select_all(action="DESELECT")
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=66, island_margin=margin)
    bpy.ops.object.mode_set(mode="OBJECT")
    return True


def combine_meshes(name: str, source_names: list[str]) -> dict[str, Any] | None:
    require_bpy()
    targets = [bpy.data.objects.get(n) for n in source_names if bpy.data.objects.get(n) is not None]
    if not targets:
        return None
    bpy.ops.object.select_all(action="DESELECT")
    for obj in targets:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = targets[0]
    bpy.ops.object.join()
    joined = bpy.context.active_object
    joined.name = safe_name(name)
    joined.data.name = safe_name(name + "_Mesh")
    return mesh_stats(joined)


def separate_by_material(name: str) -> list[dict[str, Any]]:
    require_bpy()
    target = bpy.data.objects.get(name)
    if target is None:
        return []
    bpy.ops.object.select_all(action="DESELECT")
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.separate(type="MATERIAL")
    bpy.ops.object.mode_set(mode="OBJECT")
    out = []
    for obj in bpy.context.selected_objects:
        out.append({"name": obj.name, **mesh_stats(obj)})
    return out


def select_object(name: str):
    require_bpy()
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    return obj


def deselect_all():
    require_bpy()
    bpy.ops.object.select_all(action="DESELECT")
