"""AIVIDO HQ room finisher (host-side) — Worker 1 lane: room/environment.

Builds on the live /Game/Maps/AividoHQ staging map (hub + wings + 8 human
agents already present from the character lane). Adds the production room:

  phase mats        M_Aivido_Ceil + M_Aivido_Desk materials (idempotent)
  phase arch        unified floor, wing floors, resized walls, ceilings,
                    cove rings, hub screen at human scale, rings flush,
                    entry portal, cleanup of stray test actors
  phase stations    8 agent workstations (pad/desk/monitor/trim) placed in
                    front of each human along its live facing direction
  phase collab      central ring table + chairs around the identity column
  phase command     director consoles on the dais + command pylons + deck ring
  phase lounge      breakout zone (benches + coffee table) near the entry
  phase roomlight   cove ring, collab pool, command fill, wing washes,
                    lounge + entry lights
  phase polish      signage reposition, player start at entry, save

All phases are small bridge calls with read-backs (it13 lesson). Nothing here
touches the 8 AVIDO_Human_* actors (Worker 2 lane).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.unreal.unreal_bridge import UnrealBridge  # noqa: E402

BRIDGE = UnrealBridge(host="127.0.0.1", port=6766, timeout=60)

Q = lambda s: json.dumps(str(s))  # noqa: E731


def step(name: str, code: str) -> dict:
    out = BRIDGE.execute_python(code)
    print(f"[{name}] ok={out.get('ok')} result={json.dumps(out.get('result'), default=str)[:500]}")
    if out.get("error"):
        print(f"[{name}] ERROR: {out.get('error')[:500]}")
    return out


PHASE_MATS = """
import unreal
tools = unreal.AssetToolsHelpers.get_asset_tools()
mel = unreal.MaterialEditingLibrary
def make_mat(name, base, rough):
    path = "/Game/AividoHQ"
    unreal.EditorAssetLibrary.make_directory(path)
    existing = unreal.EditorAssetLibrary.load_asset(path + "/" + name)
    if existing is not None and existing.get_class().get_name() == "Material":
        return {"name": name, "created": False, "preserved": True}
    mat = tools.create_asset(name, path, unreal.Material, unreal.MaterialFactoryNew())
    if mat is None:
        return {"name": name, "created": False, "error": "factory failed"}
    col = mel.create_material_expression(mat, unreal.MaterialExpressionConstant3Vector, -600, -200)
    col.set_editor_property("constant", unreal.LinearColor(*base))
    mel.connect_material_property(col, "", unreal.MaterialProperty.MP_BASE_COLOR)
    rough_e = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -600, 360)
    rough_e.set_editor_property("default_value", rough)
    mel.connect_material_property(rough_e, "", unreal.MaterialProperty.MP_ROUGHNESS)
    unreal.EditorAssetLibrary.save_loaded_asset(mat, False)
    return {"name": name, "created": True}

def make_emissive(name, base, emissive, rough=0.4):
    path = "/Game/AividoHQ"
    unreal.EditorAssetLibrary.make_directory(path)
    existing = unreal.EditorAssetLibrary.load_asset(path + "/" + name)
    if existing is not None and existing.get_class().get_name() == "Material":
        return {"name": name, "created": False, "preserved": True}
    mat = tools.create_asset(name, path, unreal.Material, unreal.MaterialFactoryNew())
    col = mel.create_material_expression(mat, unreal.MaterialExpressionConstant3Vector, -600, -200)
    col.set_editor_property("constant", unreal.LinearColor(*base))
    mel.connect_material_property(col, "", unreal.MaterialProperty.MP_BASE_COLOR)
    vec = mel.create_material_expression(mat, unreal.MaterialExpressionVectorParameter, -600, 60)
    vec.set_editor_property("parameter_name", name + "_Glow")
    vec.set_editor_property("default_value", unreal.LinearColor(*emissive))
    mel.connect_material_property(vec, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    rough_e = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -600, 360)
    rough_e.set_editor_property("default_value", rough)
    mel.connect_material_property(rough_e, "", unreal.MaterialProperty.MP_ROUGHNESS)
    unreal.EditorAssetLibrary.save_loaded_asset(mat, False)
    return {"name": name, "created": True}

results = []
results.append(make_mat("M_Aivido_Ceil", (0.003, 0.004, 0.006), 0.92))
results.append(make_mat("M_Aivido_Desk", (0.018, 0.020, 0.024), 0.55))
results.append(make_mat("M_Aivido_Console", (0.03, 0.033, 0.04), 0.5))
# per-agent accent materials (emissive H variants matching the character lane)
results.append(make_emissive("M_Aivido_GreenH", (0.01, 0.03, 0.015), (0.0, 6.0, 3.0)))
results.append(make_emissive("M_Aivido_VioletH", (0.025, 0.01, 0.03), (5.0, 2.2, 6.0)))
results.append(make_emissive("M_Aivido_BlueH", (0.01, 0.02, 0.03), (1.2, 3.0, 6.0)))
results.append(make_emissive("M_Aivido_GoldH", (0.03, 0.02, 0.005), (6.0, 4.6, 1.2)))
results.append(make_emissive("M_Aivido_RedH", (0.03, 0.008, 0.01), (6.0, 0.9, 1.1)))
__bridge_result__ = {"ok": True, "results": results}
"""

PHASE_ARCH_CLEAN = """
import unreal
sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
killed = []
for a in list(unreal.EditorLevelLibrary.get_all_level_actors()):
    label = a.get_actor_label()
    if label.startswith("AVIDO_Room_") or label.startswith("AVIDO_Floor_") \\
            or label.startswith("AVIDO_Portal_") or label.startswith("AVIDO_Entry_") \\
            or label in ("StaticMeshActor", "TextRenderActor") \\
            or label in ("AVIDO_Floor_Disc", "AVIDO_CD_Floor", "AVIDO_VD_Floor"):
        killed.append(label)
        sub.destroy_actor(a)
__bridge_result__ = {"ok": True, "killed": sorted(killed)}
"""

PHASE_ARCH_BUILD = """
import unreal
sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
floor_mat = unreal.load_asset("/Game/AividoHQ/M_Aivido_Floor")
wall2 = unreal.load_asset("/Game/AividoHQ/M_Aivido_Wall2")
ceil_mat = unreal.load_asset("/Game/AividoHQ/M_Aivido_Ceil")
white = unreal.load_asset("/Game/AividoHQ/M_Aivido_WhiteH")
cyan = unreal.load_asset("/Game/AividoHQ/M_Aivido_CyanH")
screen_h = unreal.load_asset("/Game/AividoHQ/M_Aivido_ScreenH2")

def sm(loc, scale, label, mesh="/Engine/BasicShapes/Cube.Cube", mat=None, yaw=0, pitch=0):
    a = sub.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(*loc), unreal.Rotator(pitch=pitch, yaw=yaw, roll=0))
    a.static_mesh_component.set_static_mesh(unreal.load_asset(mesh))
    a.set_actor_scale3d(unreal.Vector(*scale))
    a.set_actor_label(label)
    if mat is not None:
        a.static_mesh_component.set_material(0, mat)
    return a

made = []
# UNIFIED MAIN FLOOR: cylinder radius 54 m, top flush at z=0 (human feet sit at z=0)
made.append(sm((0, 0, -17.5), (108, 108, 0.35), "AVIDO_Room_Floor_Main", "/Engine/BasicShapes/Cylinder.Cylinder", floor_mat))
# wing floor slabs (fit inside the 55 m shell, top flush)
made.append(sm((3700, 0, -17.5), (36, 32, 0.35), "AVIDO_Room_Floor_Wing_E", mat=floor_mat))
made.append(sm((-3700, 0, -17.5), (36, 32, 0.35), "AVIDO_Room_Floor_Wing_W", mat=floor_mat))
# RESIZE the giant 42 m wing back walls down to human scale (9 m) and flush with the new floors
for label in ("AVIDO_CD_Wall", "AVIDO_VD_Wall"):
    for a in unreal.EditorLevelLibrary.get_all_level_actors():
        if a.get_actor_label() == label:
            side = 3700 if label == "AVIDO_CD_Wall" else -3700
            a.set_actor_location(unreal.Vector(side, -1600, 450), False, False)
            a.set_actor_scale3d(unreal.Vector(36, 0.8, 9))
            a.static_mesh_component.set_material(0, wall2)
# wing end walls (close the bays at x = 19 m and x = 55 m)
made.append(sm((1900, 0, 450), (0.8, 32, 9), "AVIDO_Room_Wing_E_Wall_E", mat=wall2))
made.append(sm((5500, 0, 450), (0.8, 32, 9), "AVIDO_Room_Wing_E_Wall_W", mat=wall2))
made.append(sm((-1900, 0, 450), (0.8, 32, 9), "AVIDO_Room_Wing_W_Wall_E", mat=wall2))
made.append(sm((-5500, 0, 450), (0.8, 32, 9), "AVIDO_Room_Wing_W_Wall_W", mat=wall2))
# CEILINGS: center disc r=40 m at 8.95 m; wing discs r=20 m layered 40 cm higher
made.append(sm((0, 0, 895), (80, 80, 0.25), "AVIDO_Room_Ceil_Center", "/Engine/BasicShapes/Cylinder.Cylinder", ceil_mat))
made.append(sm((3700, 0, 935), (40, 40, 0.2), "AVIDO_Room_Ceil_Wing_E", "/Engine/BasicShapes/Cylinder.Cylinder", ceil_mat))
made.append(sm((-3700, 0, 935), (40, 40, 0.2), "AVIDO_Room_Ceil_Wing_W", "/Engine/BasicShapes/Cylinder.Cylinder", ceil_mat))
# cove glow rings on the center ceiling
made.append(sm((0, 0, 890), (79, 79, 0.04), "AVIDO_Room_Cove_Outer", "/Engine/BasicShapes/Cylinder.Cylinder", white))
made.append(sm((0, 0, 890), (40, 40, 0.04), "AVIDO_Room_Cove_Inner", "/Engine/BasicShapes/Cylinder.Cylinder", cyan))
# HUB SCREEN at human scale (2 m - 7.5 m tall, above the dais)
for a in unreal.EditorLevelLibrary.get_all_level_actors():
    if a.get_actor_label() == "AVIDO_Hub_Screen":
        a.set_actor_location(unreal.Vector(0, -2330, 480), False, False)
        a.set_actor_rotation(unreal.Rotator(pitch=-6, yaw=0, roll=0), False)
        a.set_actor_scale3d(unreal.Vector(30, 0.6, 5.5))
        a.static_mesh_component.set_material(0, screen_h)
# floor accent rings flush on the floor
for label, z in (("AVIDO_Ring_Outer", 6), ("AVIDO_Ring_Inner", 6)):
    for a in unreal.EditorLevelLibrary.get_all_level_actors():
        if a.get_actor_label() == label:
            a.set_actor_location(unreal.Vector(0, 0, z), False, False)
# ENTRY PORTAL at the front (+Y)
made.append(sm((400, 5100, 450), (0.9, 0.9, 9), "AVIDO_Portal_Col_E", "/Engine/BasicShapes/Cylinder.Cylinder", white))
made.append(sm((-400, 5100, 450), (0.9, 0.9, 9), "AVIDO_Portal_Col_W", "/Engine/BasicShapes/Cylinder.Cylinder", white))
made.append(sm((0, 5100, 870), (9.5, 0.8, 0.9), "AVIDO_Portal_Lintel", mat=wall2))
made.append(sm((0, 5100, 6), (5, 0.3, 0.06), "AVIDO_Entry_Strip", mat=cyan))
# wing content at ABSOLUTE positions on the resized bays (idempotent)
wing_moves = {"AVIDO_CD_Swatch_0": 3700, "AVIDO_CD_Swatch_1": 3700, "AVIDO_CD_Swatch_2": 3700,
              "AVIDO_CD_Swatch_3": 3700, "AVIDO_CD_Swatch_4": 3700, "AVIDO_CD_Swatch_5": 3700,
              "AVIDO_CD_BriefStand": 3700, "AVIDO_CD_Accent": 3700,
              "AVIDO_VD_Screen_A": -3760, "AVIDO_VD_Screen_B": -3640, "AVIDO_VD_GradeStrip": -3700}
for a in unreal.EditorLevelLibrary.get_all_level_actors():
    if a.get_actor_label() in wing_moves:
        loc = a.get_actor_location()
        a.set_actor_location(unreal.Vector(wing_moves[a.get_actor_label()], loc.y, loc.z), False, False)
# wing ceilings: emissive strips along the bay fronts
made.append(sm((3700, 1620, 935), (36, 0.3, 0.06), "AVIDO_Room_Wing_E_FrontTrim", mat=cyan))
made.append(sm((-3700, 1620, 935), (36, 0.3, 0.06), "AVIDO_Room_Wing_W_FrontTrim", mat=cyan))
__bridge_result__ = {"ok": True, "actors": [m.get_actor_label() for m in made], "count": len(made)}
"""

PHASE_PADS = """
import unreal
sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
accents = {"Master": "/Game/AividoHQ/M_Aivido_CyanH", "Creative": "/Game/AividoHQ/M_Aivido_AmberH",
           "Visual": "/Game/AividoHQ/M_Aivido_MagentaH", "Technical": "/Game/AividoHQ/M_Aivido_GreenH",
           "Audio": "/Game/AividoHQ/M_Aivido_VioletH", "Animation": "/Game/AividoHQ/M_Aivido_BlueH",
           "Lighting": "/Game/AividoHQ/M_Aivido_GoldH", "VFX": "/Game/AividoHQ/M_Aivido_RedH"}

def sm(loc, scale, label, mat, mesh="/Engine/BasicShapes/Cylinder.Cylinder"):
    a = sub.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(*loc), unreal.Rotator(0, 0, 0))
    a.static_mesh_component.set_static_mesh(unreal.load_asset(mesh))
    a.set_actor_scale3d(unreal.Vector(*scale))
    a.set_actor_label(label)
    if mat is not None:
        a.static_mesh_component.set_material(0, mat)
    return a

# per-human accent floor pads + small glow trim (furniture belongs to the
# Worker 3 props lane: W3I_Station_* desks/monitors/chairs already exist)
pads = []
for a in unreal.EditorLevelLibrary.get_all_level_actors():
    label = a.get_actor_label()
    if not label.startswith("AVIDO_Human_"):
        continue
    role = label.replace("AVIDO_Human_", "")
    loc = a.get_actor_location()
    acc = unreal.load_asset(accents.get(role, "/Game/AividoHQ/M_Aivido_CyanH"))
    pads.append(sm((loc.x, loc.y, -2.5), (1.7, 1.7, 0.05), "AVIDO_Pad_" + role, acc))
    pads.append(sm((loc.x, loc.y, 1.5), (1.85, 1.85, 0.02), "AVIDO_Pad_Ring_" + role, acc))
__bridge_result__ = {"ok": True, "pads": [p.get_actor_label() for p in pads], "count": len(pads)}
"""

PHASE_COLLAB = """
import unreal
sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
table_mat = unreal.load_asset("/Game/AividoHQ/M_Aivido_Wall2")
white = unreal.load_asset("/Game/AividoHQ/M_Aivido_WhiteH")
desk_mat = unreal.load_asset("/Game/AividoHQ/M_Aivido_Desk")

def sm(loc, scale, label, mat, mesh="/Engine/BasicShapes/Cylinder.Cylinder"):
    a = sub.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(*loc), unreal.Rotator(0, 0, 0))
    a.static_mesh_component.set_static_mesh(unreal.load_asset(mesh))
    a.set_actor_scale3d(unreal.Vector(*scale))
    a.set_actor_label(label)
    if mat is not None:
        a.static_mesh_component.set_material(0, mat)
    return a

made = []
# front planning table (r=2.2 m) in the open briefing area north of the cast;
# the center ring stays clear for the identity column + W3I station ring
made.append(sm((0, 2800, 78), (4.4, 4.4, 0.08), "AVIDO_Table_Planning", table_mat))
made.append(sm((0, 2800, 83), (4.7, 4.7, 0.03), "AVIDO_Table_Planning_Rim", white))
# 4 chairs at r=3.2 m (cardinal)
for x, y in ((320, 2800), (-320, 2800), (0, 2480), (0, 3120)):
    made.append(sm((x, y, 25), (0.9, 0.9, 0.5), "AVIDO_Chair_%d_%d" % (x, y), desk_mat))
__bridge_result__ = {"ok": True, "actors": [m.get_actor_label() for m in made], "count": len(made)}
"""

PHASE_COMMAND = """
import unreal
sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
console_mat = unreal.load_asset("/Game/AividoHQ/M_Aivido_Console")
screen_h = unreal.load_asset("/Game/AividoHQ/M_Aivido_ScreenH2")
white = unreal.load_asset("/Game/AividoHQ/M_Aivido_WhiteH")
cyan = unreal.load_asset("/Game/AividoHQ/M_Aivido_CyanH")

def sm(loc, scale, label, mat, mesh="/Engine/BasicShapes/Cube.Cube", yaw=0):
    a = sub.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(*loc), unreal.Rotator(0, yaw, 0))
    a.static_mesh_component.set_static_mesh(unreal.load_asset(mesh))
    a.set_actor_scale3d(unreal.Vector(*scale))
    a.set_actor_label(label)
    if mat is not None:
        a.static_mesh_component.set_material(0, mat)
    return a

made = []
# director console center + two flanking consoles on the dais
made.append(sm((0, -1500, 75), (2.8, 1.2, 0.75), "AVIDO_Console_Center", console_mat))
made.append(sm((0, -1500, 155), (1.4, 0.08, 0.7), "AVIDO_Console_Screen", screen_h, yaw=90))
made.append(sm((450, -1500, 75), (2.2, 1.0, 0.75), "AVIDO_Console_Left", console_mat))
made.append(sm((-450, -1500, 75), (2.2, 1.0, 0.75), "AVIDO_Console_Right", console_mat))
# command pylons flanking the dais
made.append(sm((1200, -1500, 350), (1.0, 1.0, 7), "AVIDO_Command_Pylon_E", white, "/Engine/BasicShapes/Cylinder.Cylinder"))
made.append(sm((-1200, -1500, 350), (1.0, 1.0, 7), "AVIDO_Command_Pylon_W", white, "/Engine/BasicShapes/Cylinder.Cylinder"))
# presentation deck ring (r=9.5 m) flush at the dais front edge
made.append(sm((0, -1500, 6), (19, 19, 0.03), "AVIDO_Command_DeckRing", cyan, "/Engine/BasicShapes/Cylinder.Cylinder"))
# two small presentation screens flanking the hub screen
made.append(sm((1700, -2330, 480), (5, 0.3, 3.0), "AVIDO_Command_SideScreen_E", screen_h))
made.append(sm((-1700, -2330, 480), (5, 0.3, 3.0), "AVIDO_Command_SideScreen_W", screen_h))
__bridge_result__ = {"ok": True, "actors": [m.get_actor_label() for m in made], "count": len(made)}
"""

PHASE_LOUNGE = """
import unreal
sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
console_mat = unreal.load_asset("/Game/AividoHQ/M_Aivido_Console")
cyan = unreal.load_asset("/Game/AividoHQ/M_Aivido_CyanH")
desk_mat = unreal.load_asset("/Game/AividoHQ/M_Aivido_Desk")

def sm(loc, scale, label, mat, mesh="/Engine/BasicShapes/Cube.Cube", yaw=0):
    a = sub.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(*loc), unreal.Rotator(0, yaw, 0))
    a.static_mesh_component.set_static_mesh(unreal.load_asset(mesh))
    a.set_actor_scale3d(unreal.Vector(*scale))
    a.set_actor_label(label)
    if mat is not None:
        a.static_mesh_component.set_material(0, mat)
    return a

made = []
# two facing benches + coffee table (breakout zone between stations and entry)
made.append(sm((0, 4300, 45), (6, 1.2, 0.9), "AVIDO_Lounge_Bench_N", console_mat))
made.append(sm((0, 3900, 45), (6, 1.2, 0.9), "AVIDO_Lounge_Bench_S", console_mat))
made.append(sm((0, 4100, 20), (2.6, 1.2, 0.4), "AVIDO_Lounge_Table", desk_mat))
made.append(sm((0, 4100, 42), (2.8, 1.4, 0.04), "AVIDO_Lounge_Trim", cyan))
# floor pads under the benches
made.append(sm((0, 4300, -2), (5, 2.4, 0.04), "AVIDO_Lounge_Pad_N", cyan))
made.append(sm((0, 3900, -2), (5, 2.4, 0.04), "AVIDO_Lounge_Pad_S", cyan))
__bridge_result__ = {"ok": True, "actors": [m.get_actor_label() for m in made], "count": len(made)}
"""

PHASE_ROOMLIGHT_CLEAN = """
import unreal
sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
killed = 0
for a in list(unreal.EditorLevelLibrary.get_all_level_actors()):
    if a.get_actor_label().startswith("AVIDO_Light_Room"):
        sub.destroy_actor(a)
        killed += 1
__bridge_result__ = {"ok": True, "killed": killed}
"""

PHASE_ROOMLIGHT = """
import unreal
sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)

def sp(loc, color, intensity, radius, label):
    a = sub.spawn_actor_from_class(unreal.PointLight, unreal.Vector(*loc), unreal.Rotator(0, 0, 0))
    a.set_actor_label(label)
    c = a.light_component
    c.set_light_color(unreal.LinearColor(*color))
    c.set_intensity(intensity)
    c.set_attenuation_radius(radius)
    return a

import math
lights = []
# cove ring: 8 soft pools under the ceiling edge (r=38 m)
for i in range(8):
    ang = math.radians(i * 45 + 22.5)
    x, y = 3800 * math.cos(ang), 3800 * math.sin(ang)
    lights.append(sp((x, y, 850), (0.55, 0.7, 1.0), 22000, 2600, "AVIDO_Light_Room_Cove_%d" % i))
# collaboration pool over the front planning table
lights.append(sp((0, 2800, 700), (0.35, 0.8, 0.95), 16000, 2600, "AVIDO_Light_Room_Collab"))
# command zone fill (two)
lights.append(sp((900, -1900, 700), (0.4, 0.55, 0.85), 20000, 2400, "AVIDO_Light_Room_Cmd_E"))
lights.append(sp((-900, -1900, 700), (0.4, 0.55, 0.85), 20000, 2400, "AVIDO_Light_Room_Cmd_W"))
# wing ceiling washes
lights.append(sp((3700, 0, 700), (1.0, 0.55, 0.2), 24000, 2800, "AVIDO_Light_Room_Wing_E"))
lights.append(sp((-3700, 0, 700), (1.0, 0.35, 0.85), 24000, 2800, "AVIDO_Light_Room_Wing_W"))
# lounge + entry
lights.append(sp((0, 4100, 550), (0.6, 0.72, 1.0), 16000, 2400, "AVIDO_Light_Room_Lounge"))
lights.append(sp((0, 5100, 500), (0.7, 0.85, 1.0), 14000, 2400, "AVIDO_Light_Room_Entry"))
__bridge_result__ = {"ok": True, "lights": [l.get_actor_label() for l in lights], "count": len(lights)}
"""

PHASE_POLISH = """
import unreal
sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)

# 1. signage at human scale (previous signs floated at 30 m+ above the ceiling)
def set_sign(label, loc, size, rot, color):
    for a in unreal.EditorLevelLibrary.get_all_level_actors():
        if a.get_actor_label() == label:
            a.set_actor_location(unreal.Vector(*loc), False, False)
            a.set_actor_rotation(unreal.Rotator(pitch=rot[0], yaw=rot[1], roll=rot[2]), False)
            comp = a.get_component_by_class(unreal.TextRenderComponent)
            comp.set_world_size(size)
            comp.set_text_render_color(unreal.Color(int(color[0]*255), int(color[1]*255), int(color[2]*255), 255))
            return True
    return False

signs = []
signs.append(("AVIDO_Sign_Entry", (0, 5150, 950), 260, (0, 0, 0), (0.9, 0.95, 1.0)))
signs.append(("AVIDO_Sign_Master", (0, -2350, 1250), 90, (0, 0, 0), (0.6, 0.95, 1.0)))
signs.append(("AVIDO_Sign_Central", (0, -2350, 1020), 90, (0, 0, 0), (0.6, 0.95, 1.0)))
signs.append(("AVIDO_Sign_Creative", (3700, -1450, 760), 100, (0, 180, 0), (1.0, 0.75, 0.35)))
signs.append(("AVIDO_Sign_Visual", (-3700, -1450, 760), 100, (0, 0, 0), (1.0, 0.55, 0.85)))
missing = []
for label, loc, size, rot, color in signs:
    if not set_sign(label, loc, size, rot, color):
        missing.append(label)

# 2. player start at the entry portal, facing the room (-Y)
ps = None
for a in unreal.EditorLevelLibrary.get_all_level_actors():
    if a.get_actor_label() == "AVIDO_PlayerStart":
        ps = a
        break
if ps is None:
    ps = sub.spawn_actor_from_class(unreal.PlayerStart, unreal.Vector(0, 5100, 250), unreal.Rotator(0, -90, 0))
    ps.set_actor_label("AVIDO_PlayerStart")
ps.set_actor_location(unreal.Vector(0, 5050, 250), False, False)
ps.set_actor_rotation(unreal.Rotator(pitch=0, yaw=-90, roll=0), False)

# 3. hero camera at the entry, framed on the command wall
cam = None
for a in unreal.EditorLevelLibrary.get_all_level_actors():
    if a.get_actor_label() == "AVIDO_ShotCam":
        cam = a
        break
if cam is None:
    cam = sub.spawn_actor_from_class(unreal.CameraActor, unreal.Vector(0, 4800, 320), unreal.Rotator(0, -90, 0))
    cam.set_actor_label("AVIDO_ShotCam")
cam.set_actor_location(unreal.Vector(0, 4700, 320), False, False)
cam.set_actor_rotation(unreal.Rotator(pitch=-6, yaw=-90, roll=0), False)

# 4. exposure: manual, slightly darker so emissives pop
pp = None
for a in unreal.EditorLevelLibrary.get_all_level_actors():
    if a.get_actor_label() == "AVIDO_Exposure":
        pp = a
        break
if pp is None:
    pp = sub.spawn_actor_from_class(unreal.PostProcessVolume, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
    pp.set_actor_label("AVIDO_Exposure")
s = pp.settings
s.set_editor_property("auto_exposure_method", unreal.AutoExposureMethod.AEM_MANUAL)
s.set_editor_property("auto_exposure_bias", -0.5)
s.set_editor_property("auto_exposure_apply_physical_camera_exposure", False)
pp.set_editor_property("unbound", True)

unreal.EditorLoadingAndSavingUtils.save_current_level()
__bridge_result__ = {"ok": True, "missing_signs": missing, "saved": True}
"""


def phase_mats() -> None:
    step("mats.create", PHASE_MATS)


def phase_arch() -> None:
    step("arch.clean", PHASE_ARCH_CLEAN)
    step("arch.build", PHASE_ARCH_BUILD)


def phase_stations() -> None:
    step("pads.clean", """
import unreal
sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
killed = 0
for a in list(unreal.EditorLevelLibrary.get_all_level_actors()):
    label = a.get_actor_label()
    if label.startswith("AVIDO_Pad_"):
        sub.destroy_actor(a)
        killed += 1
__bridge_result__ = {"ok": True, "killed": killed}
""")
    step("pads.build", PHASE_PADS)


def phase_collab() -> None:
    step("collab.clean", """
import unreal
sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
killed = 0
for a in list(unreal.EditorLevelLibrary.get_all_level_actors()):
    label = a.get_actor_label()
    if label.startswith("AVIDO_Table_") or label.startswith("AVIDO_Chair_"):
        sub.destroy_actor(a)
        killed += 1
__bridge_result__ = {"ok": True, "killed": killed}
""")
    step("collab.build", PHASE_COLLAB)


def phase_command() -> None:
    step("command.clean", """
import unreal
sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
killed = 0
for a in list(unreal.EditorLevelLibrary.get_all_level_actors()):
    label = a.get_actor_label()
    if label.startswith("AVIDO_Console_") or label.startswith("AVIDO_Command_"):
        sub.destroy_actor(a)
        killed += 1
__bridge_result__ = {"ok": True, "killed": killed}
""")
    step("command.build", PHASE_COMMAND)


def phase_lounge() -> None:
    step("lounge.clean", """
import unreal
sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
killed = 0
for a in list(unreal.EditorLevelLibrary.get_all_level_actors()):
    label = a.get_actor_label()
    if label.startswith("AVIDO_Lounge_"):
        sub.destroy_actor(a)
        killed += 1
__bridge_result__ = {"ok": True, "killed": killed}
""")
    step("lounge.build", PHASE_LOUNGE)


PHASE_CLEAN_PADS = """
import unreal
sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
for a in list(unreal.EditorLevelLibrary.get_all_level_actors()):
    if a.get_actor_label().startswith("AVIDO_Pad_"):
        sub.destroy_actor(a)
"""

PHASE_CLEAN_COLLAB = """
import unreal
sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
for a in list(unreal.EditorLevelLibrary.get_all_level_actors()):
    if a.get_actor_label().startswith("AVIDO_Table_") or a.get_actor_label().startswith("AVIDO_Chair_"):
        sub.destroy_actor(a)
"""

PHASE_CLEAN_COMMAND = """
import unreal
sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
for a in list(unreal.EditorLevelLibrary.get_all_level_actors()):
    if a.get_actor_label().startswith("AVIDO_Console_") or a.get_actor_label().startswith("AVIDO_Command_"):
        sub.destroy_actor(a)
"""

PHASE_CLEAN_LOUNGE = """
import unreal
sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
for a in list(unreal.EditorLevelLibrary.get_all_level_actors()):
    if a.get_actor_label().startswith("AVIDO_Lounge_"):
        sub.destroy_actor(a)
"""


def phase_roomlight() -> None:
    step("roomlight.clean", PHASE_ROOMLIGHT_CLEAN)
    step("roomlight.build", PHASE_ROOMLIGHT)


def phase_polish() -> None:
    step("polish.run", PHASE_POLISH)


def phase_all() -> None:
    """Atomic rebuild: every room section in ONE bridge call so a concurrent
    lane reload cannot interleave and wipe half-built furniture."""
    combined = "\n\n".join([
        PHASE_ARCH_CLEAN,
        PHASE_ARCH_BUILD,
        PHASE_CLEAN_PADS, PHASE_PADS,
        PHASE_CLEAN_COLLAB, PHASE_COLLAB,
        PHASE_CLEAN_COMMAND, PHASE_COMMAND,
        PHASE_CLEAN_LOUNGE, PHASE_LOUNGE,
        PHASE_ROOMLIGHT_CLEAN, PHASE_ROOMLIGHT,
        PHASE_POLISH,
    ])
    step("all.atomic", combined)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True,
                        choices=["mats", "arch", "stations", "collab", "command", "lounge",
                                 "roomlight", "polish", "all"])
    args = parser.parse_args()
    start = time.time()
    {"mats": phase_mats, "arch": phase_arch, "stations": phase_stations,
     "collab": phase_collab, "command": phase_command, "lounge": phase_lounge,
     "roomlight": phase_roomlight, "polish": phase_polish, "all": phase_all}[args.phase]()
    print(f"PHASE {args.phase} elapsed={time.time() - start:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())