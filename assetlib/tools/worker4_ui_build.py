"""Worker 4 takeover — Aivido HQ in-world Game UI (state displays).

Builds three game-style UI boards on the command deck side screens of
/Game/Maps/AividoHQ using existing Aivido materials + TextRender:

  AIVIDO_UI_Agents_Board   8-agent roster (Worker 2 cast, real roles)
  AIVIDO_UI_Missions_Board production mission tracker (real states)
  AIVIDO_UI_Status_Board   integration status (real worker states)

UMG interactive widgets are not buildable via UE 5.8 python API
(WidgetBlueprintEditorLibrary absent) — documented in the handoff.
Saves the map, verifies text/actors, captures no proof (PIE proofs live in
assetlib/proof/ via separate capture run).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.unreal.unreal_bridge import UnrealBridge  # noqa: E402

BRIDGE = UnrealBridge(host="127.0.0.1", port=6766, timeout=180)

AGENTS_TEXT = (
    "AIVIDO AGENTS ROSTER\n\n"
    "MASTER    - COMMAND\n"
    "CREATIVE  - DESIGN\n"
    "VISUAL    - REVIEW\n"
    "TECHNICAL - BUILD\n"
    "AUDIO     - SOUND\n"
    "ANIMATION - MOTION\n"
    "LIGHTING  - LOOK DEV\n"
    "VFX       - EFFECTS"
)
MISSIONS_TEXT = (
    "PRODUCTION MISSIONS\n\n"
    "M1 HQ ENVIRONMENT   - COMPLETE\n"
    "M2 CAST INTEGRATION - COMPLETE\n"
    "M3 PROPS KIT        - COMPLETE\n"
    "M4 GAME UI          - ACTIVE\n"
    "M5 FINAL QA         - PENDING"
)
STATUS_TEXT = (
    "HQ INTEGRATION STATUS\n\n"
    "W1 ROOM  - OK\n"
    "W2 CAST  - OK\n"
    "W3 PROPS - OK\n"
    "W4 UI    - ACTIVE\n"
    "W5 QA    - PENDING\n\n"
    "INTEGRATION: 88%"
)

code = r"""
import unreal
AGENTS_TEXT = __AGENTS__
MISSIONS_TEXT = __MISSIONS__
STATUS_TEXT = __STATUS__
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
les.load_level("/Game/Maps/AividoHQ")
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)

# clean previous attempt
for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor):
    if a.get_actor_label().startswith("AIVIDO_UI_"):
        subsystem.destroy_actor(a)

screens = {}
for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.StaticMeshActor):
    label = a.get_actor_label()
    if label in ("AVIDO_Command_SideScreen_E", "AVIDO_Command_SideScreen_W"):
        screens[label] = a.get_actor_location()

built, errors = [], []

def board(label_suffix, screen_label, dx, dy, dz, size_x, size_z, text, text_z, text_size):
    anchor = screens.get(screen_label)
    if anchor is None:
        errors.append(label_suffix + ": screen missing " + screen_label)
        return
    panel = subsystem.spawn_actor_from_class(
        unreal.StaticMeshActor,
        unreal.Vector(anchor.x + dx, anchor.y + dy, anchor.z + dz),
        unreal.Rotator(0, 0, 0))
    comp = panel.get_component_by_class(unreal.StaticMeshComponent)
    comp.set_static_mesh(unreal.EditorAssetLibrary.load_asset("/Engine/BasicShapes/Cube"))
    comp.set_world_scale3d(unreal.Vector(size_x / 100.0, 6.0 / 100.0, size_z / 100.0))
    mat = unreal.EditorAssetLibrary.load_asset("/Game/AividoHQ/M_Aivido_ScreenH2")
    if mat is not None:
        comp.set_editor_property("override_materials", [mat])
    panel.set_actor_label("AIVIDO_UI_" + label_suffix + "_Panel")
    text_actor = subsystem.spawn_actor_from_class(
        unreal.TextRenderActor,
        unreal.Vector(anchor.x + dx, anchor.y + dy - 6.0, anchor.z + dz + text_z),
        unreal.Rotator(0, 180, 0))
    tr = text_actor.get_component_by_class(unreal.TextRenderComponent)
    tr.set_editor_property("text", unreal.Text(text))
    tr.set_editor_property("text_render_color", unreal.Color(0.05, 0.8, 1.0, 1.0))
    tr.set_editor_property("world_size", float(text_size))
    tr.set_editor_property("horizontal_alignment", unreal.HorizTextAligment.EHTA_LEFT)
    tr.set_editor_property("vertical_alignment", unreal.VerticalTextAligment.EVRTA_TEXT_BOTTOM)
    text_actor.set_actor_label("AIVIDO_UI_" + label_suffix + "_Text")
    built.extend(["AIVIDO_UI_" + label_suffix + "_Panel", "AIVIDO_UI_" + label_suffix + "_Text"])

# boards mounted just in front (y +45 toward room) of each side screen
board("Agents",  "AVIDO_Command_SideScreen_E", 0, 45, 0,  260, 300, AGENTS_TEXT,  90, 22)
board("Missions", "AVIDO_Command_SideScreen_W", 0, 45, 0,  260, 300, MISSIONS_TEXT, 90, 22)
# status board centered on hub wall, between side screens
hub = None
for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.StaticMeshActor):
    if a.get_actor_label() == "AVIDO_Hub_Wall":
        hub = a.get_actor_location()
if hub is None:
    errors.append("Status: hub wall missing")
else:
    panel = subsystem.spawn_actor_from_class(
        unreal.StaticMeshActor, unreal.Vector(hub.x, hub.y + 45, hub.z - 600),
        unreal.Rotator(0, 0, 0))
    comp = panel.get_component_by_class(unreal.StaticMeshComponent)
    comp.set_static_mesh(unreal.EditorAssetLibrary.load_asset("/Engine/BasicShapes/Cube"))
    comp.set_world_scale3d(unreal.Vector(2.2, 0.06, 2.6))
    mat = unreal.EditorAssetLibrary.load_asset("/Game/AividoHQ/M_Aivido_ScreenH2")
    if mat is not None:
        comp.set_editor_property("override_materials", [mat])
    panel.set_actor_label("AIVIDO_UI_Status_Panel")
    text_actor = subsystem.spawn_actor_from_class(
        unreal.TextRenderActor, unreal.Vector(hub.x, hub.y + 39, hub.z - 480),
        unreal.Rotator(0, 0, 0))
    tr = text_actor.get_component_by_class(unreal.TextRenderComponent)
    tr.set_editor_property("text", unreal.Text(STATUS_TEXT))
    tr.set_editor_property("text_render_color", unreal.Color(0.05, 0.8, 1.0, 1.0))
    tr.set_editor_property("world_size", 22.0)
    tr.set_editor_property("horizontal_alignment", unreal.HorizTextAligment.EHTA_LEFT)
    tr.set_editor_property("vertical_alignment", unreal.VerticalTextAligment.EVRTA_TEXT_BOTTOM)
    text_actor.set_actor_label("AIVIDO_UI_Status_Text")
    built.extend(["AIVIDO_UI_Status_Panel", "AIVIDO_UI_Status_Text"])

saved = unreal.EditorLevelLibrary.save_current_level()

# verify: reload from disk and count
les.load_level("/Game/Maps/AividoHQ")
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
ui = [a.get_actor_label() for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor)
      if a.get_actor_label().startswith("AIVIDO_UI_")]
texts = {}
for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.TextRenderActor):
    label = a.get_actor_label()
    if label.startswith("AIVIDO_UI_"):
        tr = a.get_component_by_class(unreal.TextRenderComponent)
        texts[label] = len(str(tr.get_editor_property("text")))
__bridge_result__ = {"ok": len(errors) == 0 and len(ui) == 6 and len(texts) == 3 and bool(saved),
    "built": built, "ui_actors": ui, "text_lengths": texts, "errors": errors,
    "saved": bool(saved), "level": world.get_path_name()}
"""

code = code.replace("__AGENTS__", json.dumps(AGENTS_TEXT))
code = code.replace("__MISSIONS__", json.dumps(MISSIONS_TEXT))
code = code.replace("__STATUS__", json.dumps(STATUS_TEXT))

out = BRIDGE.execute_python(code)
r = out.get("result") or {}
print("ok:", r.get("ok"), "| saved:", r.get("saved"))
print("ui_actors:", r.get("ui_actors"))
print("text_lengths:", r.get("text_lengths"))
for e in r.get("errors", []):
    print("ERROR:", e)
if not r:
    print("raw:", json.dumps(out, default=str)[:700])

