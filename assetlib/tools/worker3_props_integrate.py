"""Worker 5 integration helper — place the Worker 3 props kit into any map.

Default is a DRY RUN (prints the plan). Use --apply to spawn into the target
map, verify floor contact, save, and leave the map loaded.

Layout: 4 workstations (desk + chair + monitor + terminal) on a 900cm ring
facing center, presentation board north, 2 storage cabinets east, 2 plants at
south corners, server rack north-east, 2 lanterns flanking the north entry.

Usage:
  python assetlib/tools/worker3_props_integrate.py                 # dry run
  python assetlib/tools/worker3_props_integrate.py --apply         # into AividoHQ
  python assetlib/tools/worker3_props_integrate.py --map /Game/Maps/X --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.unreal.unreal_bridge import UnrealBridge  # noqa: E402

BRIDGE = UnrealBridge(host="127.0.0.1", port=6766, timeout=180)
DEFAULT_MAP = "/Game/Maps/AividoHQ"
PROPS_DIR = "/Game/AividoHQ/Props"

BP = lambda n: f"{PROPS_DIR}/BPs/BP_Aivido_Prop_{n}"  # noqa: E731

# label -> (asset_path, loc, yaw_deg)
LAYOUT = {
    "W3I_Station_W_Desk":     (BP("Desk"), (-900, 0, 0), 90),
    "W3I_Station_W_Chair":    (BP("Chair"), (-1250, 0, 0), 90),
    "W3I_Station_W_Monitor":  (BP("Monitor"), (-900, -120, 75), 90),
    "W3I_Station_N_Desk":     (BP("Desk"), (0, 900, 0), 180),
    "W3I_Station_N_Chair":    (BP("Chair"), (0, 1250, 0), 180),
    "W3I_Station_N_Monitor":  (BP("Monitor"), (-120, 900, 75), 180),
    "W3I_Station_E_Desk":     (BP("Desk"), (900, 0, 0), 270),
    "W3I_Station_E_Chair":    (BP("Chair"), (1250, 0, 0), 270),
    "W3I_Station_E_Monitor":  (BP("Monitor"), (900, -120, 75), 270),
    "W3I_Station_S_Desk":     (BP("Desk"), (0, -900, 0), 0),
    "W3I_Station_S_Chair":    (BP("Chair"), (0, -1250, 0), 0),
    "W3I_Station_S_Monitor":  (BP("Monitor"), (-120, -900, 75), 0),
    "W3I_Terminal_W":         (BP("Terminal"), (-700, 500, 0), 135),
    "W3I_Terminal_E":         (BP("Terminal"), (700, -500, 0), 315),
    "W3I_PresentationBoard":  (BP("PresentationBoard"), (0, 1800, 0), 180),
    "W3I_Cabinet_E1":         (BP("StorageCabinet"), (1800, 300, 0), 270),
    "W3I_Cabinet_E2":         (BP("StorageCabinet"), (1800, 700, 0), 270),
    "W3I_Plant_SW":           (BP("PlantDecor"), (-1800, -1700, 0), 0),
    "W3I_Plant_SE":           (BP("PlantDecor"), (1800, -1700, 0), 0),
    "W3I_ServerRack":         (BP("ServerRack"), (1500, 1500, 0), 225),
    "W3I_Lantern_Body":       (f"{PROPS_DIR}/Lantern/StaticMeshes/LanternPole_Body", (0, 2100, 0), 0),
    "W3I_Lantern_Chain":      (f"{PROPS_DIR}/Lantern/StaticMeshes/LanternPole_Chain", (0, 2100, 144.24), 0),
    "W3I_Lantern_Lantern":    (f"{PROPS_DIR}/Lantern/StaticMeshes/LanternPole_Lantern", (0, 2100, 151.57), 0),
}
LANTERN_SCALE = 0.0562


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", default=DEFAULT_MAP)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if not args.apply:
        print(f"DRY RUN — would place {len(LAYOUT)} prop actors into {args.map}")
        for label, (path, loc, yaw) in LAYOUT.items():
            print(f"  {label:28s} {path.rsplit('/', 1)[-1]:24s} at {loc} yaw={yaw}")
        return 0

    entries = ", ".join(
        f"({json.dumps(label)}, {json.dumps(path)}, {json.dumps(list(loc))}, {yaw})"
        for label, (path, loc, yaw) in LAYOUT.items()
    )
    code = f"""
import unreal
map_path = {json.dumps(args.map)}
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
les.load_level(map_path)
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
old = [a for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor)
       if a.get_actor_label().startswith("W3I_")]
for a in old:
    subsystem.destroy_actor(a)
spawned, errors = [], []
lantern_parts = {{"Lantern_Body", "Lantern_Chain", "Lantern_Lantern"}}
for label, path, loc, yaw in [{entries}]:
    asset = unreal.EditorAssetLibrary.load_asset(path)
    if asset is None:
        errors.append(label + ": asset missing " + path)
        continue
    if label.endswith(tuple(lantern_parts)):
        actor = subsystem.spawn_actor_from_object(asset, unreal.Vector(*loc), unreal.Rotator(0, yaw, 0))
        if actor is not None:
            actor.set_actor_scale3d(unreal.Vector({LANTERN_SCALE}, {LANTERN_SCALE}, {LANTERN_SCALE}))
    else:
        gen = asset.generated_class() if hasattr(asset, "generated_class") else None
        if gen is None:
            errors.append(label + ": no generated class")
            continue
        actor = subsystem.spawn_actor_from_class(gen, unreal.Vector(*loc), unreal.Rotator(0, yaw, 0))
    if actor is None:
        errors.append(label + ": spawn failed")
        continue
    actor.set_actor_label(label)
    spawned.append(label)
saved = unreal.EditorLevelLibrary.save_current_level()
contacts = []
for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor):
    label = a.get_actor_label()
    if not label.startswith("W3I_") or "Lantern" in label:
        continue
    zmin = 1e9
    for c in a.get_components_by_class(unreal.StaticMeshComponent):
        sm = c.get_editor_property("static_mesh")
        if sm is None:
            continue
        b = sm.get_bounds()
        wt = c.get_world_transform()
        for sx in (-1, 1):
            for sy in (-1, 1):
                for sz in (-1, 1):
                    corner = unreal.Vector(b.origin.x + sx * b.box_extent.x,
                                           b.origin.y + sy * b.box_extent.y,
                                           b.origin.z + sz * b.box_extent.z)
                    zmin = min(zmin, wt.transform_location(corner).z)
    contacts.append({{"label": label, "z_min": round(zmin, 2), "contact": abs(zmin) < 5.0 or "Monitor" in label}})
__bridge_result__ = {{"ok": len(errors) == 0 and len(spawned) == {len(LAYOUT)} and saved,
    "spawned": len(spawned), "errors": errors, "contacts": contacts,
    "level": world.get_path_name()}}
"""
    out = BRIDGE.execute_python(code)
    r = out.get("result") or {}
    print(json.dumps(r, indent=1, default=str)[:2500])
    if out.get("error"):
        print("error:", str(out["error"])[:600])
        return 1
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
