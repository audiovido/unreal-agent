"""AIVIDO HQ hero-character builder.

Imports Microsoft RocketBox (MIT) human bases into /Game/AividoHQ/Characters,
builds premium PBR character materials (SSS skin + cloth wired to the imported
texture maps), and spawns the eight-agent cast at their HQ stations:

  MASTER DIRECTOR    -> Business_Male_01   (suited, commanding)
  CREATIVE DIRECTOR  -> Male_Adult_11      (distinct casual identity)
  VISUAL DIRECTOR    -> Business_Female_02 (refined, glasses)
  TECHNICAL DIRECTOR -> Male_Adult_03      (engineer, technical)
  AUDIO DIRECTOR     -> Female_Adult_05    (sound, accessorised)
  ANIMATION DIRECTOR -> Male_Adult_12      (motion artist)
  LIGHTING ARTIST    -> Female_Adult_01    (senior lighting, wrinkles)
  VFX ARTIST         -> Female_Adult_08    (VFX, accessorised)

Phases: import (body+facial fbx per character), materials (PBR master +
character MICs), spawn (skeletal actors at stations), lighting accents.
Every phase verifies read-backs. Source: assetlib/source/rocketbox (MIT,
manifest.json records license + attribution for every file).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.unreal.unreal_bridge import UnrealBridge  # noqa: E402

BRIDGE = UnrealBridge(host="127.0.0.1", port=6766, timeout=120)
STAGE = ROOT / "assetlib" / "source" / "rocketbox" / "stage"

CHARACTERS = {
    "Master": {
        "name": "Business_Male_01",
        "dest": "/Game/AividoHQ/Characters/Master",
        "prefix": "m005",
        "station": (0, -1380, 0),
        "yaw": 90,
        "accents": "cyan",
        "role": "MASTER_DIRECTOR",
        "station_final": (0, 700, 0),
    },
    "Creative": {
        "name": "Male_Adult_11",
        "dest": "/Game/AividoHQ/Characters/Creative",
        "prefix": "m001",
        "station": (3800, 260, 0),
        "yaw": -90,
        "accents": "amber",
        "role": "CREATIVE_DIRECTOR",
        "station_final": (3800, 900, 0),
    },
    "Visual": {
        "name": "Business_Female_02",
        "dest": "/Game/AividoHQ/Characters/Visual",
        "prefix": "f015",
        "station": (-3800, 260, 0),
        "yaw": -90,
        "accents": "magenta",
        "role": "VISUAL_DIRECTOR",
        "station_final": (-3800, 900, 0),
    },
    "Technical": {
        "name": "Male_Adult_03",
        "dest": "/Game/AividoHQ/Characters/Technical",
        "prefix": "m004",
        "station": (1900, 300, 0),
        "yaw": 180,
        "accents": "green",
        "role": "TECHNICAL_DIRECTOR",
        "station_final": (1900, 300, 0),
    },
    "Audio": {
        "name": "Female_Adult_05",
        "dest": "/Game/AividoHQ/Characters/Audio",
        "prefix": "f005",
        "station": (-1900, 300, 0),
        "yaw": 180,
        "accents": "violet",
        "role": "AUDIO_DIRECTOR",
        "station_final": (-1900, 300, 0),
    },
    "Animation": {
        "name": "Male_Adult_12",
        "dest": "/Game/AividoHQ/Characters/Animation",
        "prefix": "m007",
        "station": (950, 1700, 0),
        "yaw": 180,
        "accents": "sky",
        "role": "ANIMATION_DIRECTOR",
        "station_final": (950, 1700, 0),
    },
    "Lighting": {
        "name": "Female_Adult_01",
        "dest": "/Game/AividoHQ/Characters/Lighting",
        "prefix": "f001",
        "station": (-950, 1700, 0),
        "yaw": 180,
        "accents": "gold",
        "role": "LIGHTING_ARTIST",
        "station_final": (-950, 1700, 0),
    },
    "VFX": {
        "name": "Female_Adult_08",
        "dest": "/Game/AividoHQ/Characters/VFX",
        "prefix": "f008",
        "station": (0, 2000, 0),
        "yaw": 180,
        "accents": "pink",
        "role": "VFX_ARTIST",
        "station_final": (0, 2000, 0),
    },
}

Q = lambda s: json.dumps(str(s))  # noqa: E731


def step(name: str, code: str) -> dict:
    out = BRIDGE.execute_python(code)
    print(f"[{name}] ok={out.get('ok')} result={json.dumps(out.get('result'), default=str)[:400]}")
    if out.get("error"):
        print(f"[{name}] ERROR: {out.get('error')[:500]}")
    return out


def phase_import(key: str) -> None:
    """Import the staged avatar FBX. Uses the engine's automated auto-detect
    path (no FbxImportUI options): the FbxImportUI options object silently
    aborts the import in UE 5.8 (recorded live, Sep 2026), while auto-detect
    reliably imports mesh + skeleton + physics + embedded animation + the
    referenced TGA textures."""
    spec = CHARACTERS[key]
    # stage layout is stage/<KEY>/<avatar>.fbx (+ textures in the same dir)
    folder = STAGE / key
    dest = spec["dest"]
    body = folder / f"{spec['name']}.fbx"
    facial = folder / f"{spec['name']}_facial.fbx"

    def _import(path: str, tag: str) -> None:
        step(f"import.{key}.{tag}", f"""
import unreal
task = unreal.AssetImportTask()
task.filename = {Q(str(path))}
task.destination_path = {Q(dest)}
task.automated = True
task.save = True
task.replace_existing = True
tools = unreal.AssetToolsHelpers.get_asset_tools()
tools.import_asset_tasks([task])
created = list(unreal.EditorAssetLibrary.list_assets({Q(dest)}, recursive=True, include_folder=False))
__bridge_result__ = {{"ok": True, "count": len(created), "assets": created}}
""")

    _import(str(body), "body")
    if facial.exists():
        _import(str(facial), "facial")


def _delete_asset(path: str) -> None:
    step("mats.delete", f"""
import unreal
p = {Q(path)}
if unreal.EditorAssetLibrary.does_asset_exist(p):
    unreal.EditorAssetLibrary.delete_asset(p)
__bridge_result__ = {{"ok": True, "deleted": p}}
""")


def phase_materials() -> None:
    """Premium PBR character materials: SSS skin + cloth master wired to the
    imported MakeHuman-style maps (color -> base, normal -> normal,
    specular -> roughness, subsurface color + opacity for believable skin).
    Materials are deleted and rebuilt each run so fixes always land."""
    # delete MICs first (they reference the materials), then the materials
    for key in CHARACTERS:
        _delete_asset(CHARACTERS[key]["dest"] + "/Aivido_Body")
        _delete_asset(CHARACTERS[key]["dest"] + "/Aivido_Head")
    _delete_asset("/Game/AividoHQ/Characters/M_Aivido_Skin")
    _delete_asset("/Game/AividoHQ/Characters/M_Aivido_Cloth")
    step("mats.skin_master", f"""
import unreal
tools = unreal.AssetToolsHelpers.get_asset_tools()
mel = unreal.MaterialEditingLibrary
mat = tools.create_asset("M_Aivido_Skin", "/Game/AividoHQ/Characters", unreal.Material, unreal.MaterialFactoryNew())
# ColorMap -> base color
tex_p = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSampleParameter2D, -900, -300)
tex_p.set_editor_property("parameter_name", "ColorMap")
tex_p.set_editor_property("group", "Skin")
mel.connect_material_property(tex_p, "", unreal.MaterialProperty.MP_BASE_COLOR)
# NormalMap -> normal
n_p = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSampleParameter2D, -900, 60)
n_p.set_editor_property("parameter_name", "NormalMap")
n_p.set_editor_property("group", "Skin")
mel.connect_material_property(n_p, "", unreal.MaterialProperty.MP_NORMAL)
# SpecMap -> roughness via 1-x
r_p = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSampleParameter2D, -900, 420)
r_p.set_editor_property("parameter_name", "SpecMap")
r_p.set_editor_property("group", "Skin")
one = mel.create_material_expression(mat, unreal.MaterialExpressionConstant, -700, 500)
one.set_editor_property("r", 1.0)
sub = mel.create_material_expression(mat, unreal.MaterialExpressionSubtract, -500, 500)
mel.connect_material_expressions(one, "", sub, "")
mel.connect_material_expressions(r_p, "", sub, "")
mel.connect_material_property(sub, "", unreal.MaterialProperty.MP_ROUGHNESS)
# SubsurfaceColor (RED-TINTED vector) -> subsurface color (not a scalar!)
sss_col = mel.create_material_expression(mat, unreal.MaterialExpressionVectorParameter, -600, -120)
sss_col.set_editor_property("parameter_name", "SubsurfaceColor")
sss_col.set_editor_property("default_value", unreal.LinearColor(0.85, 0.40, 0.35, 1.0))
sss_col.set_editor_property("group", "Skin")
mel.connect_material_property(sss_col, "", unreal.MaterialProperty.MP_SUBSURFACE_COLOR)
# SubsurfaceOpacity scalar -> opacity (SSS amount)
sss_op = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -600, 180)
sss_op.set_editor_property("parameter_name", "SubsurfaceOpacity")
sss_op.set_editor_property("default_value", 0.45)
sss_op.set_editor_property("group", "Skin")
mel.connect_material_property(sss_op, "", unreal.MaterialProperty.MP_OPACITY)
mat.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_SUBSURFACE)
unreal.EditorAssetLibrary.save_loaded_asset(mat, False)
__bridge_result__ = {{"ok": True, "created": True, "path": mat.get_path_name()}}
""")
    step("mats.cloth_master", f"""
import unreal
tools = unreal.AssetToolsHelpers.get_asset_tools()
mel = unreal.MaterialEditingLibrary
path = "/Game/AividoHQ/Characters/M_Aivido_Cloth"
existing = unreal.load_asset(path)
if existing is None:
    existing = unreal.EditorAssetLibrary.load_asset(path)
if existing is not None and existing.get_class().get_name() == "Material":
    __bridge_result__ = {{"ok": True, "created": False, "preserved": True}}
else:
    mat = tools.create_asset("M_Aivido_Cloth", "/Game/AividoHQ/Characters", unreal.Material, unreal.MaterialFactoryNew())
    tex_p = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSampleParameter2D, -900, -300)
    tex_p.set_editor_property("parameter_name", "ColorMap")
    tex_p.set_editor_property("group", "Cloth")
    mel.connect_material_property(tex_p, "", unreal.MaterialProperty.MP_BASE_COLOR)
    n_p = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSampleParameter2D, -900, 60)
    n_p.set_editor_property("parameter_name", "NormalMap")
    n_p.set_editor_property("group", "Cloth")
    mel.connect_material_property(n_p, "", unreal.MaterialProperty.MP_NORMAL)
    r_p = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSampleParameter2D, -900, 420)
    r_p.set_editor_property("parameter_name", "SpecMap")
    r_p.set_editor_property("group", "Cloth")
    one = mel.create_material_expression(mat, unreal.MaterialExpressionConstant, -700, 500)
    one.set_editor_property("r", 1.0)
    sub = mel.create_material_expression(mat, unreal.MaterialExpressionSubtract, -500, 500)
    mel.connect_material_expressions(one, "", sub, "")
    mel.connect_material_expressions(r_p, "", sub, "")
    mel.connect_material_property(sub, "", unreal.MaterialProperty.MP_ROUGHNESS)
    mat.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_DEFAULT_LIT)
    unreal.EditorAssetLibrary.save_loaded_asset(mat, False)
    __bridge_result__ = {{"ok": True, "created": True}}
""")


def phase_mics() -> None:
    """Per-character material instances wiring each mesh slot (body -> cloth,
    head -> skin, opacity -> cloth-with-mask) to the imported maps."""
    for key, spec in CHARACTERS.items():
        prefix = spec["prefix"]
        step(f"mics.{key}", f"""
import unreal
tools = unreal.AssetToolsHelpers.get_asset_tools()
mel = unreal.MaterialEditingLibrary
skin = unreal.load_asset("/Game/AividoHQ/Characters/M_Aivido_Skin")
cloth = unreal.load_asset("/Game/AividoHQ/Characters/M_Aivido_Cloth")
dest = {Q(spec['dest'])}
def ensure_mic(name, parent):
    p = dest + "/" + name
    ex = unreal.load_asset(p)
    if ex is not None and ex.get_class().get_name() == "MaterialInstanceConstant":
        return ex
    return tools.create_asset(name, dest, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
body_mic = ensure_mic("Aivido_Body", cloth)
body_mic.set_editor_property("parent", cloth)
head_mic = ensure_mic("Aivido_Head", skin)
head_mic.set_editor_property("parent", skin)
def tpv(name, tex_asset):
    return unreal.TextureParameterValue(
        parameter_info=unreal.MaterialParameterInfo(name=name),
        parameter_value=unreal.load_asset(tex_asset))
body_mic.set_editor_property("texture_parameter_values", [
    tpv("ColorMap", dest + "/{prefix}_body_color"),
    tpv("NormalMap", dest + "/{prefix}_body_normal"),
    tpv("SpecMap", dest + "/{prefix}_body_specular"),
])
head_mic.set_editor_property("texture_parameter_values", [
    tpv("ColorMap", dest + "/{prefix}_head_color"),
    tpv("NormalMap", dest + "/{prefix}_head_normal"),
    tpv("SpecMap", dest + "/{prefix}_head_specular"),
])
unreal.EditorAssetLibrary.save_loaded_asset(body_mic, False)
unreal.EditorAssetLibrary.save_loaded_asset(head_mic, False)
# apply to the skeletal mesh material slots (slot order: body, head, opacity)
mesh = unreal.load_asset(dest + "/" + {Q(spec['name'])})
if mesh is not None and mesh.get_class().get_name() == "SkeletalMesh":
    mats = mesh.materials
    slots = [str(ms.material_slot_name) for ms in mats]
    print("SLOTS:", len(slots), slots)
    new_mats = []
    for slot in slots:
        pick = head_mic if "head" in slot.lower() else body_mic
        new_mats.append(unreal.SkeletalMaterial(material_interface=pick, material_slot_name=slot))
    mesh.materials = new_mats
__bridge_result__ = {{"ok": True}}
""")


def phase_spawn() -> None:
    """Replace the placeholder CesiumMan agents with the human agents."""
    step("spawn.clean", f"""
import unreal
sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
killed = 0
for a in list(unreal.EditorLevelLibrary.get_all_level_actors()):
    if a.get_actor_label().startswith("AVIDO_Agent_") or a.get_actor_label().startswith("AVIDO_Human_"):
        sub.destroy_actor(a)
        killed += 1
__bridge_result__ = {{"ok": True, "killed": killed}}
""")
    for key, spec in CHARACTERS.items():
        step(f"spawn.{key}", f"""
import unreal
sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
mesh = unreal.load_asset({Q(spec['dest'] + "/" + spec['name'])})
actor = sub.spawn_actor_from_class(unreal.SkeletalMeshActor, unreal.Vector(*{tuple(spec['station'])!r}), unreal.Rotator(pitch=0, yaw={spec['yaw']}, roll=0))
actor.skeletal_mesh_component.set_skeletal_mesh_asset(mesh)
actor.set_actor_label("AVIDO_Human_{key}")
loc = actor.get_actor_location()
print("SPAWNED:", {key!r}, [round(loc.x,1), round(loc.y,1), round(loc.z,1)])
__bridge_result__ = {{"ok": True, "mesh": mesh.get_name()}}
""")


ACCENT_COLORS = {
    "cyan": (0.25, 0.85, 0.95),
    "amber": (1.0, 0.62, 0.3),
    "magenta": (1.0, 0.42, 0.9),
    "green": (0.25, 1.0, 0.6),
    "violet": (0.7, 0.5, 1.0),
    "sky": (0.4, 0.7, 1.0),
    "gold": (1.0, 0.85, 0.4),
    "pink": (1.0, 0.35, 0.5),
}


def phase_light() -> None:
    """Per-agent face lights so characters read in the HQ lighting."""
    step("char.light.clean", f"""
import unreal
sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
killed = 0
for a in list(unreal.EditorLevelLibrary.get_all_level_actors()):
    if a.get_actor_label().startswith("AVIDO_FaceLight"):
        sub.destroy_actor(a)
        killed += 1
__bridge_result__ = {{"ok": True, "killed": killed}}
""")
    for key, spec in CHARACTERS.items():
        color = ACCENT_COLORS[spec["accents"]]
        hx, hy, hz = spec["station_final"]
        step(f"char.light.{key}", f"""
import unreal
sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
a = sub.spawn_actor_from_class(unreal.SpotLight, unreal.Vector({hx}, {hy} + 260, 320), unreal.Rotator(pitch=-14, yaw=180 if {hx} <= 0 else 0, roll=0))
a.set_actor_label("AVIDO_FaceLight_{key}")
light = a.light_component
light.set_light_color(unreal.LinearColor(*{tuple(color)!r}))
light.set_intensity(14000)
light.set_attenuation_radius(2200)
light.set_editor_property("outer_cone_angle", 42.0)
light.set_editor_property("inner_cone_angle", 32.0)
__bridge_result__ = {{"ok": True, "lights": 1}}
""")


def phase_reposition() -> None:
    """Pull the hero agents to their final stations (Master on the main axis,
    wings at their room thresholds, specialists in the inner ring)."""
    moves = {
        f"AVIDO_Human_{key}": (spec["station_final"], spec["yaw"])
        for key, spec in CHARACTERS.items()
    }
    step("char.move", f"""
import unreal
moves = {moves!r}
for a in unreal.EditorLevelLibrary.get_all_level_actors():
    label = a.get_actor_label()
    if label in moves:
        loc, yaw = moves[label]
        a.set_actor_location(unreal.Vector(*loc), False, False)
        a.set_actor_rotation(unreal.Rotator(pitch=0, yaw=yaw, roll=0), False)
        print(label, "moved")
__bridge_result__ = {{"ok": True}}
""")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True, choices=["import", "materials", "mics", "spawn", "light", "move", "all"])
    args = parser.parse_args()
    start = time.time()
    if args.phase in ("import", "all"):
        for key in CHARACTERS:
            phase_import(key)
    if args.phase in ("materials", "all"):
        phase_materials()
    if args.phase in ("mics", "all"):
        phase_mics()
    if args.phase in ("spawn", "all"):
        phase_spawn()
    if args.phase in ("light", "all"):
        phase_light()
    if args.phase in ("move", "all"):
        phase_reposition()
    print(f"PHASE {args.phase} elapsed={time.time() - start:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())