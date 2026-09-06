"""Worker 3 takeover — build the Aivido HQ props kit (integration-ready).

Builds /Game/AividoHQ/Props/* (8 prop Blueprints + prop material set + Lantern
kit) and the staging map /Game/Maps/AividoHQ_PropsStage, then verifies asset
counts, floor contact and material wiring, captures proof, and restores the
AividoHQ level so the integration editor state is preserved.

Phases (small bridge calls per the it13 lesson):
  mats      prop material set (/Game/AividoHQ/Props/Mats)
  bps       8 prop Blueprints (/Game/AividoHQ/Props/BPs)
  lantern   duplicate Lantern meshes into /Game/AividoHQ/Props/Lantern
  stage     create staging map + floor + lights
  spawn     spawn props into the staging map (floor contact)
  verify    read-back counts + contacts + evidence JSON + screenshot
  restore   reload /Game/Maps/AividoHQ

Usage: python assetlib/tools/worker3_props_build.py [--phase all|mats|bps|...]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.unreal.unreal_bridge import UnrealBridge  # noqa: E402

BRIDGE = UnrealBridge(host="127.0.0.1", port=6766, timeout=180)
STAGE_MAP = "/Game/Maps/AividoHQ_PropsStage"
PROPS_DIR = "/Game/AividoHQ/Props"
EVIDENCE_PATH = ROOT / "assetlib" / "reports" / "worker3_props_evidence.json"
PROOF_PNG = ROOT / "assetlib" / "reports" / "worker3_props_stage.png"

MATERIALS = [
    ("M3_PropWood",    (0.35, 0.22, 0.12), None, 0.65),
    ("M3_PropMetal",   (0.24, 0.26, 0.30), None, 0.35),
    ("M3_PropPlastic", (0.07, 0.07, 0.09), None, 0.50),
    ("M3_PropScreen",  (0.02, 0.03, 0.04), (0.10, 0.50, 0.80), 0.20),
    ("M3_PropGlow",    (0.05, 0.04, 0.03), (1.00, 0.60, 0.15), 0.30),
    ("M3_PropFabric",  (0.14, 0.19, 0.28), None, 0.85),
    ("M3_PropLeaf",    (0.10, 0.42, 0.16), None, 0.70),
    ("M3_PropBoard",   (0.85, 0.85, 0.87), None, 0.80),
    ("M3_PropFloor",   (0.28, 0.30, 0.33), None, 0.90),
]

CUBE = "/Engine/BasicShapes/Cube"
CYLINDER = "/Engine/BasicShapes/Cylinder"
SPHERE = "/Engine/BasicShapes/Sphere"

# name, parts: (mesh, size(scale3d), loc, rot, material)
PROPS = {
    "BP_Aivido_Prop_Desk": [
        (CUBE, (160, 80, 4),   (0, 0, 73),  None, "M3_PropWood"),
        (CUBE, (4, 70, 70),    (-76, 0, 35), None, "M3_PropMetal"),
        (CUBE, (4, 70, 70),    (76, 0, 35),  None, "M3_PropMetal"),
        (CUBE, (150, 4, 30),   (0, -36, 55), None, "M3_PropMetal"),
    ],
    "BP_Aivido_Prop_Chair": [
        (CUBE, (50, 50, 6),  (0, 0, 45),  None, "M3_PropFabric"),
        (CUBE, (50, 6, 50),  (0, -25, 70), None, "M3_PropFabric"),
        (CUBE, (8, 8, 40),   (0, 0, 23),  None, "M3_PropMetal"),
        (CUBE, (46, 46, 4),  (0, 0, 2),   None, "M3_PropMetal"),
    ],
    "BP_Aivido_Prop_Monitor": [
        (CUBE, (60, 4, 36),  (0, 0, 32),  None, "M3_PropScreen"),
        (CUBE, (6, 6, 18),   (0, 0, 14),  None, "M3_PropPlastic"),
        (CUBE, (30, 20, 3),  (0, 0, 1.5), None, "M3_PropPlastic"),
    ],
    "BP_Aivido_Prop_Terminal": [
        (CUBE, (60, 40, 120), (0, 0, 70),                  None, "M3_PropPlastic"),
        (CUBE, (50, 6, 40),   (0, -20, 110),               (-20, 0, 0), "M3_PropScreen"),
        (CUBE, (50, 36, 10),  (0, 0, 5),                   None, "M3_PropMetal"),
    ],
    "BP_Aivido_Prop_PresentationBoard": [
        (CUBE, (240, 6, 120), (0, 0, 110),  None, "M3_PropBoard"),
        (CUBE, (240, 8, 6),   (0, 0, 172),  None, "M3_PropGlow"),
        (CUBE, (8, 10, 50),   (-112, 0, 25), None, "M3_PropMetal"),
        (CUBE, (8, 10, 50),   (112, 0, 25),  None, "M3_PropMetal"),
    ],
    "BP_Aivido_Prop_StorageCabinet": [
        (CUBE, (100, 50, 196), (0, 0, 98),   None, "M3_PropMetal"),
        (CUBE, (44, 2, 180),   (-24, 26, 98), None, "M3_PropPlastic"),
        (CUBE, (44, 2, 180),   (24, 26, 98),  None, "M3_PropPlastic"),
        (CUBE, (104, 6, 8),    (0, 0, 192),   None, "M3_PropGlow"),
    ],
    "BP_Aivido_Prop_PlantDecor": [
        (CYLINDER, (40, 40, 40), (0, 0, 20),  None, "M3_PropPlastic"),
        (SPHERE,   (50, 50, 50), (0, 0, 78),  None, "M3_PropLeaf"),
        (SPHERE,   (34, 34, 34), (16, 8, 96), None, "M3_PropLeaf"),
    ],
    "BP_Aivido_Prop_ServerRack": [
        (CUBE, (80, 100, 200), (0, 0, 100),  None, "M3_PropMetal"),
        (CUBE, (60, 2, 4),     (0, 51, 170), None, "M3_PropGlow"),
        (CUBE, (60, 2, 4),     (0, 51, 150), None, "M3_PropGlow"),
        (CUBE, (60, 2, 10),    (0, 51, 30),  None, "M3_PropPlastic"),
    ],
}

LANTERN_MESHES = [
    "/Game/Showcase/Props/Lantern/StaticMeshes/LanternPole_Body",
    "/Game/Showcase/Props/Lantern/StaticMeshes/LanternPole_Chain",
    "/Game/Showcase/Props/Lantern/StaticMeshes/LanternPole_Lantern",
]

evidence: dict = {"tool": "worker3_props_build", "phases": {}, "started": time.strftime("%Y-%m-%d %H:%M:%S")}


def step(name: str, code: str) -> dict:
    out = BRIDGE.execute_python(code)
    ok = out.get("ok")
    result = out.get("result")
    print(f"[{name}] ok={ok} result={json.dumps(result, default=str)[:300]}")
    evidence["phases"][name] = {"ok": bool(ok), "result": result if not isinstance(result, str) else result[:2000]}
    if out.get("error"):
        print(f"[{name}] ERROR: {str(out['error'])[:600]}")
        evidence["phases"][name]["error"] = str(out["error"])[:2000]
    return out


def phase_mats() -> bool:
    mats = ", ".join(
        f"({json.dumps(n)}, {json.dumps(list(b))}, {json.dumps(list(e)) if e else 'None'}, {r})"
        for n, b, e, r in MATERIALS
    )
    code = f"""
import unreal
tools = unreal.AssetToolsHelpers.get_asset_tools()
mel = unreal.MaterialEditingLibrary
unreal.EditorAssetLibrary.make_directory("{PROPS_DIR}/Mats")
made, preserved = [], []
for name, base, emissive, rough in [{mats}]:
    path = "{PROPS_DIR}/Mats/" + name
    existing = unreal.EditorAssetLibrary.load_asset(path)
    if existing is not None and existing.get_class().get_name() == "Material":
        preserved.append(name)
        continue
    mat = tools.create_asset(name, "{PROPS_DIR}/Mats", unreal.Material, unreal.MaterialFactoryNew())
    if mat is None:
        raise RuntimeError("factory failed for " + name)
    col = mel.create_material_expression(mat, unreal.MaterialExpressionConstant3Vector, -600, -200)
    col.set_editor_property("constant", unreal.LinearColor(*base))
    mel.connect_material_property(col, "", unreal.MaterialProperty.MP_BASE_COLOR)
    rgh = mel.create_material_expression(mat, unreal.MaterialExpressionConstant, -600, 60)
    rgh.set_editor_property("r", float(rough))
    mel.connect_material_property(rgh, "", unreal.MaterialProperty.MP_ROUGHNESS)
    if emissive is not None:
        vec = mel.create_material_expression(mat, unreal.MaterialExpressionConstant3Vector, -600, 300)
        vec.set_editor_property("constant", unreal.LinearColor(*emissive))
        mel.connect_material_property(vec, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    mel.recompile_material(mat)
    made.append(name)
saved = unreal.EditorAssetLibrary.save_directory("{PROPS_DIR}/Mats", False)
__bridge_result__ = {{"ok": True, "made": made, "preserved": preserved, "saved": bool(saved)}}
"""
    out = step("mats", code)
    return bool(out.get("ok"))


def build_one_bp(name: str, parts: list) -> dict:
    parts_json = ", ".join(
        f"({json.dumps(mesh)}, {json.dumps(list(s))}, {json.dumps(list(l))}, "
        f"{json.dumps(list(r)) if r else 'None'}, {json.dumps(m)})"
        for mesh, s, l, r, m in parts
    )
    code = f"""
import unreal
bp_path = "{PROPS_DIR}/BPs/{name}"
unreal.EditorAssetLibrary.make_directory("{PROPS_DIR}/BPs")
bp = unreal.EditorAssetLibrary.load_asset(bp_path)
if bp is not None:
    unreal.EditorAssetLibrary.delete_asset(bp_path)
    bp = None
tools = unreal.AssetToolsHelpers.get_asset_tools()
factory = unreal.BlueprintFactory()
factory.set_editor_property("parent_class", unreal.Actor)
bp = tools.create_asset("{name}", "{PROPS_DIR}/BPs", None, factory)
if bp is None:
    __bridge_result__ = {{"ok": False, "error": "BlueprintFactory failed"}}
else:
    subsystem = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    handles = subsystem.k2_gather_subobject_data_for_blueprint(bp)
    root_handle = None
    for handle in handles:
        data = unreal.SubobjectDataBlueprintFunctionLibrary.get_data(handle)
        if data is not None and unreal.SubobjectDataBlueprintFunctionLibrary.is_root_component(data):
            root_handle = handle
            break
    if root_handle is None:
        __bridge_result__ = {{"ok": False, "error": "root handle not found"}}
    else:
        added, errors = [], []
        mesh_cache = {{}}
        for i, (mesh_path, scale, loc, rot, mat_name) in enumerate([{parts_json}]):
            if mesh_path not in mesh_cache:
                mesh_cache[mesh_path] = unreal.EditorAssetLibrary.load_asset(mesh_path)
            mesh = mesh_cache[mesh_path]
            mat = unreal.EditorAssetLibrary.load_asset("{PROPS_DIR}/Mats/" + mat_name)
            params = unreal.AddNewSubobjectParams()
            params.set_editor_property("parent_handle", root_handle)
            params.set_editor_property("new_class", unreal.StaticMeshComponent)
            params.set_editor_property("blueprint_context", bp)
            new_handle, fail_reason = subsystem.add_new_subobject(params=params)
            if not unreal.SubobjectDataBlueprintFunctionLibrary.is_handle_valid(new_handle):
                errors.append("part" + str(i) + ": " + str(fail_reason))
                continue
            subsystem.rename_subobject(new_handle, unreal.Text("Part" + str(i)))
            data = unreal.SubobjectDataBlueprintFunctionLibrary.get_data(new_handle)
            obj = unreal.SubobjectDataBlueprintFunctionLibrary.get_object(data)
            obj.set_editor_property("static_mesh", mesh)
            obj.set_editor_property("relative_location", unreal.Vector(*loc))
            if rot is not None:
                obj.set_editor_property("relative_rotation", unreal.Rotator(rot[0], rot[1], rot[2]))
            obj.set_editor_property("relative_scale3d", unreal.Vector(scale[0] / 100.0, scale[1] / 100.0, scale[2] / 100.0))
            if mat is not None:
                obj.set_editor_property("override_materials", [mat])
            added.append("Part" + str(i))
        unreal.BlueprintEditorLibrary.compile_blueprint(bp)
        saved = unreal.EditorAssetLibrary.save_loaded_asset(bp, False)
        gen_class = bp.generated_class()
        __bridge_result__ = {{"ok": len(errors) == 0,
            "parts_added": added, "errors": errors, "saved": bool(saved),
            "gen_class": str(gen_class) if gen_class else None}}
"""
    out = step(f"bp.{name}", code)
    return out.get("result") if isinstance(out.get("result"), dict) else {"ok": False}


def phase_bps() -> bool:
    all_ok = True
    summary = {}
    for name, parts in PROPS.items():
        res = build_one_bp(name, parts)
        summary[name] = res
        if not res.get("ok"):
            all_ok = False
    evidence["phases"]["bps_summary"] = summary
    return all_ok


def phase_lantern() -> bool:
    meshes = ", ".join(json.dumps(p) for p in LANTERN_MESHES)
    code = f"""
import unreal
unreal.EditorAssetLibrary.make_directory("{PROPS_DIR}/Lantern/StaticMeshes")
duplicated, missing = [], []
for src in [{meshes}]:
    dst = "{PROPS_DIR}/Lantern/StaticMeshes/" + src.rsplit("/", 1)[-1]
    if unreal.EditorAssetLibrary.does_asset_exist(dst):
        duplicated.append(dst)
        continue
    if not unreal.EditorAssetLibrary.does_asset_exist(src):
        missing.append(src)
        continue
    if unreal.EditorAssetLibrary.duplicate_asset(src, dst) is None:
        missing.append(src + " (dup failed)")
    else:
        duplicated.append(dst)
bounds = {{}}
for dst in duplicated:
    sm = unreal.EditorAssetLibrary.load_asset(dst)
    if sm is not None:
        b = sm.get_bounds()
        bounds[dst.rsplit("/", 1)[-1]] = {{
            "origin": [b.origin.x, b.origin.y, b.origin.z],
            "extent": [b.box_extent.x, b.box_extent.y, b.box_extent.z]
        }}
unreal.EditorAssetLibrary.save_directory("{PROPS_DIR}/Lantern", False)
__bridge_result__ = {{"ok": len(missing) == 0, "duplicated": duplicated, "missing": missing, "bounds": bounds}}
"""
    out = step("lantern", code)
    return bool(out.get("ok"))


def phase_stage() -> bool:
    out = BRIDGE.create_default_level(STAGE_MAP)
    print(f"[stage.create] ok={out.get('ok')} result={json.dumps(out.get('result'), default=str)[:200]}")
    evidence["phases"]["stage.create"] = {"ok": bool(out.get("ok")), "result": out.get("result")}
    if not out.get("ok"):
        return False
    code = f"""
import unreal
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
old = [a for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor)
       if a.get_actor_label().startswith("W3_") or a.get_actor_label().startswith("W3P_")]
for a in old:
    subsystem.destroy_actor(a)
floor = subsystem.spawn_actor_from_class(
    unreal.StaticMeshActor, unreal.Vector(0, 0, -5))
comp = floor.get_component_by_class(unreal.StaticMeshComponent)
comp.set_static_mesh(unreal.EditorAssetLibrary.load_asset("{CUBE}"))
comp.set_world_scale3d(unreal.Vector(30, 30, 0.1))
comp.set_editor_property("override_materials", [unreal.EditorAssetLibrary.load_asset("{PROPS_DIR}/Mats/M3_PropFloor")])
floor.set_actor_label("W3_Floor")
sun = subsystem.spawn_actor_from_class(
    unreal.DirectionalLight, unreal.Vector(0, 0, 900))
sun.set_actor_rotation(unreal.Rotator(pitch=-45, yaw=35, roll=0), False)
sun.set_actor_label("W3_Sun")
sun_comp = sun.get_component_by_class(unreal.DirectionalLightComponent)
if sun_comp is not None:
    sun_comp.set_editor_property("intensity", 6.0)
sky = subsystem.spawn_actor_from_class(
    unreal.SkyLight, unreal.Vector(0, 0, 600))
sky.set_actor_label("W3_SkyLight")
sky_comp = sky.get_component_by_class(unreal.SkyLightComponent)
if sky_comp is not None:
    sky_comp.set_editor_property("intensity", 2.0)
unreal.EditorLevelLibrary.save_current_level()
__bridge_result__ = {{"ok": True, "level": world.get_path_name(), "cleaned": len(old)}}
"""
    out2 = step("stage.build", code)
    return bool(out2.get("ok"))


def phase_spawn() -> bool:
    bp_names = ", ".join(json.dumps(n) for n in PROPS)
    code = f"""
import unreal
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
les.load_level("{STAGE_MAP}")
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
unreal.EditorAssetLibrary.make_directory("{PROPS_DIR}/BPs")
subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
old = [a for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor)
       if a.get_actor_label().startswith("W3P_")]
for a in old:
    subsystem.destroy_actor(a)
spawned, errors = [], []
bp_names = [{bp_names}]
for i, name in enumerate(bp_names):
    bp = unreal.EditorAssetLibrary.load_asset("{PROPS_DIR}/BPs/" + name)
    if bp is None:
        errors.append(name + ": bp missing")
        continue
    gen = bp.generated_class()
    if gen is None:
        errors.append(name + ": no gen class")
        continue
    col = i % 4
    row = i // 4
    loc = unreal.Vector(-600 + col * 400, 300 + row * 500, 0)
    actor = subsystem.spawn_actor_from_class(gen, loc, unreal.Rotator(0, 0, 0))
    if actor is None:
        errors.append(name + ": spawn failed")
        continue
    actor.set_actor_label("W3P_" + name.replace("BP_Aivido_Prop_", ""))
    origin, extent = actor.get_actor_bounds(False)
    spawned.append({{"name": name, "label": actor.get_actor_label(),
        "z_min": round(origin.z - extent.z, 2), "loc": [loc.x, loc.y, 0]}})
__bridge_result__ = {{"ok": len(errors) == 0 and len(spawned) == 8, "spawned": spawned, "errors": errors}}
"""
    out = step("spawn.bps", code)
    if not out.get("ok"):
        return False

    lantern_code = f"""
import unreal
subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
for a in [a for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.StaticMeshActor)
          if a.get_actor_label().startswith("W3P_Lantern")]:
    subsystem.destroy_actor(a)
parts = []
for i, path in enumerate([{", ".join(json.dumps(p) for p in LANTERN_MESHES)}]):
    dst = "{PROPS_DIR}/Lantern/StaticMeshes/" + path.rsplit("/", 1)[-1]
    sm = unreal.EditorAssetLibrary.load_asset(dst)
    if sm is None:
        __bridge_result__ = {{"ok": False, "error": "missing " + dst}}
        break
    b = sm.get_bounds()
    parts.append({{"path": dst, "mesh": sm,
        "origin": [b.origin.x, b.origin.y, b.origin.z],
        "extent": [b.box_extent.x, b.box_extent.y, b.box_extent.z]}})
else:
    target_h = 180.0
    heights = [p["extent"][2] * 2 for p in parts]
    total_h = sum(heights)
    s = target_h / total_h if total_h > 0 else 1.0
    spawned = []
    z = 0.0
    for p in parts:
        bottom_off = (p["origin"][2] - p["extent"][2]) * s
        loc = unreal.Vector(900, 300, z - bottom_off)
        actor = subsystem.spawn_actor_from_object(p["mesh"], loc, unreal.Rotator(0, 0, 0))
        if actor is None:
            __bridge_result__ = {{"ok": False, "error": "spawn failed " + p["path"]}}
            break
        actor.set_actor_scale3d(unreal.Vector(s, s, s))
        actor.set_actor_label("W3P_Lantern_" + p["path"].rsplit("/", 1)[-1].replace("LanternPole_", ""))
        origin, extent = actor.get_actor_bounds(False)
        spawned.append({{"part": p["path"].rsplit("/", 1)[-1], "z_min": round(origin.z - extent.z, 2),
            "z_max": round(origin.z + extent.z, 2), "scale": round(s, 4)}})
        z += heights[parts.index(p)] * s
    else:
        __bridge_result__ = {{"ok": len(spawned) == 3, "spawned": spawned, "scale": round(s, 4)}}
"""
    out2 = step("spawn.lantern", lantern_code)
    if not out2.get("ok"):
        return False
    save_code = f"""
import unreal
saved = unreal.EditorLevelLibrary.save_current_level()
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
__bridge_result__ = {{"ok": bool(saved), "level": world.get_path_name()}}
"""
    out3 = step("spawn.save", save_code)
    return bool(out3.get("ok"))


def phase_verify() -> bool:
    code = f"""
import unreal
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
les.load_level("{STAGE_MAP}")
ar = unreal.AssetRegistryHelpers.get_asset_registry()
props = ar.get_assets_by_path("{PROPS_DIR}", recursive=True)
by_class = {{}}
for a in props:
    cls = str(a.asset_class_path.asset_name)
    by_class[cls] = by_class.get(cls, 0) + 1
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
contacts = []
for attempt in range(40):
    actors = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor)
    if len(actors) > 0:
        break
    try:
        unreal.EditorLevelLibrary.editor_tick()
    except Exception:
        pass
for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor):
    label = a.get_actor_label()
    if not label.startswith("W3P_"):
        continue
    zmin = 1e9
    n_meshes = 0
    for c in a.get_components_by_class(unreal.StaticMeshComponent):
        sm = c.get_editor_property("static_mesh")
        if sm is None:
            continue
        n_meshes += 1
        b = sm.get_bounds()
        wt = c.get_world_transform()
        for sx in (-1, 1):
            for sy in (-1, 1):
                for sz in (-1, 1):
                    corner = unreal.Vector(b.origin.x + sx * b.box_extent.x,
                                           b.origin.y + sy * b.box_extent.y,
                                           b.origin.z + sz * b.box_extent.z)
                    zmin = min(zmin, wt.transform_location(corner).z)
    contacts.append({{"label": label, "meshes": n_meshes, "z_min": round(zmin, 2),
        "floor_contact": abs(zmin) < 5.0}})
# material wiring check on monitor BP via SCS templates
bp = unreal.EditorAssetLibrary.load_asset("{PROPS_DIR}/BPs/BP_Aivido_Prop_Monitor")
mat_ok = False
if bp is not None:
    subsystem = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    handles = subsystem.k2_gather_subobject_data_for_blueprint(bp)
    for handle in handles:
        data = unreal.SubobjectDataBlueprintFunctionLibrary.get_data(handle)
        obj = unreal.SubobjectDataBlueprintFunctionLibrary.get_object(data)
        if obj is not None and obj.get_class().get_name() == "StaticMeshComponent":
            om = obj.get_editor_property("override_materials")
            if om and "Screen" in om[0].get_name():
                mat_ok = True
lantern = [a for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.StaticMeshActor)
           if a.get_actor_label().startswith("W3P_Lantern")]
bp_contacts = [c for c in contacts if "Lantern" not in c["label"]]
lantern_contacts = [c for c in contacts if "Lantern" in c["label"]]
bp_ok = len(bp_contacts) == 8 and all(c["floor_contact"] and c["meshes"] >= 3 for c in bp_contacts)
lantern_ok = len(lantern) == 3 and len(lantern_contacts) == 3
__bridge_result__ = {{"ok": bp_ok and mat_ok and lantern_ok,
    "props_assets": len(props), "by_class": by_class, "contacts": contacts,
    "monitor_material_wired": mat_ok, "lantern_actors": len(lantern),
    "level": world.get_path_name()}}
"""
    out = step("verify", code)
    if not out.get("ok"):
        return False

    cap = BRIDGE.capture_unreal_viewport()
    print(f"[capture] {json.dumps(cap.get('result'), default=str)[:200]}")
    cap_path = None
    if isinstance(cap.get("result"), dict):
        cap_path = cap["result"].get("path")
    deadline = time.time() + 30
    while time.time() < deadline and not (cap_path and Path(cap_path).is_file()):
        time.sleep(2)
    if cap_path and Path(cap_path).is_file():
        shutil.copyfile(cap_path, PROOF_PNG)
        evidence["proof_png"] = str(PROOF_PNG)
        evidence["proof_png_bytes"] = PROOF_PNG.stat().st_size
        evidence["proof_source"] = cap_path
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    evidence["phases"]["capture"] = {"ok": True, "path": str(PROOF_PNG) if PROOF_PNG.is_file() else None}
    EVIDENCE_PATH.write_text(json.dumps(evidence, indent=1, default=str), encoding="utf-8")
    print(f"[evidence] {EVIDENCE_PATH}")
    return PROOF_PNG.is_file()


def phase_restore() -> bool:
    code = """
import unreal
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
loaded = les.load_level("/Game/Maps/AividoHQ")
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
__bridge_result__ = {"ok": bool(loaded), "level": world.get_path_name()}
"""
    out = step("restore", code)
    return bool(out.get("ok"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", default="all")
    args = ap.parse_args()
    phases = {
        "mats": phase_mats,
        "bps": phase_bps,
        "lantern": phase_lantern,
        "stage": phase_stage,
        "spawn": phase_spawn,
        "verify": phase_verify,
        "restore": phase_restore,
    }
    if args.phase == "all":
        ok = True
        for name, fn in phases.items():
            r = fn()
            print(f"=== phase {name}: {'OK' if r else 'FAIL'}")
            if name != "restore":
                ok = ok and r
            if not r and name != "restore":
                break
        evidence["overall_ok"] = ok
        EVIDENCE_PATH.write_text(json.dumps(evidence, indent=1, default=str), encoding="utf-8")
        return 0 if ok else 1
    fn = phases.get(args.phase)
    if fn is None:
        print("unknown phase")
        return 2
    r = fn()
    print(f"=== phase {args.phase}: {'OK' if r else 'FAIL'}")
    return 0 if r else 1


if __name__ == "__main__":
    raise SystemExit(main())
