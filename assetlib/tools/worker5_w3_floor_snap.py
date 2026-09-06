"""Worker 5: snap W3I_ props in AividoHQ to the true floor (z=0, proven by the
8 integrated characters) and monitors onto desk tops. Saves the map."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.unreal.unreal_bridge import UnrealBridge  # noqa: E402

BRIDGE = UnrealBridge(host="127.0.0.1", port=6766, timeout=180)

code = r"""
import unreal
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
les.load_level("/Game/Maps/AividoHQ")
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()

w3i = [a for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor)
       if a.get_actor_label().startswith("W3I_")]
by_label = {a.get_actor_label(): a for a in w3i}


def zmin_max(actor):
    zmin, zmax = 1e9, -1e9
    for c in actor.get_components_by_class(unreal.StaticMeshComponent):
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
                    z = wt.transform_location(corner).z
                    zmin = min(zmin, z)
                    zmax = max(zmax, z)
    return (zmin if zmin < 1e9 else None), (zmax if zmax > -1e9 else None)


def shift(actor, dz):
    loc = actor.get_actor_location()
    actor.set_actor_location(unreal.Vector(loc.x, loc.y, loc.z + dz), False, False)


fixed, errors = [], []

# 1) floor props: bottom -> 0
for label, a in by_label.items():
    if any(k in label for k in ("Monitor", "Lantern", "_Desk")):
        continue
    zmin, _ = zmin_max(a)
    if zmin is None:
        errors.append(label + ": no bounds")
        continue
    if abs(zmin) > 0.5:
        shift(a, -zmin)
        fixed.append({"label": label, "dz": round(-zmin, 2), "to": 0.0})

# 2) desks: bottom -> 0
for label, a in by_label.items():
    if label.endswith("_Desk"):
        zmin, _ = zmin_max(a)
        if zmin is None:
            errors.append(label + ": no bounds")
            continue
        if abs(zmin) > 0.5:
            shift(a, -zmin)
            fixed.append({"label": label, "dz": round(-zmin, 2), "to": 0.0})

# 3) monitors: onto desk top
for label, a in by_label.items():
    if not label.endswith("_Monitor"):
        continue
    desk_label = label.replace("_Monitor", "_Desk")
    desk = by_label.get(desk_label)
    if desk is None:
        errors.append(label + ": desk missing")
        continue
    dloc = desk.get_actor_location()
    aloc = a.get_actor_location()
    a.set_actor_location(unreal.Vector(dloc.x, dloc.y, aloc.z), False, False)
    zmin, _ = zmin_max(a)
    dtop = 75.0  # desk top height above desk root
    if zmin is not None:
        shift(a, dtop - zmin)
        fixed.append({"label": label, "dz": round(dtop - zmin, 2), "to": dtop})

# 4) lantern kit: body bottom -> 0, chain -> 144.24, head -> 151.57
lantern_targets = {"W3I_Lantern_Body": 0.0, "W3I_Lantern_Chain": 144.24, "W3I_Lantern_Lantern": 151.57}
for label, target in lantern_targets.items():
    a = by_label.get(label)
    if a is None:
        errors.append(label + ": missing")
        continue
    zmin, _ = zmin_max(a)
    if zmin is None:
        errors.append(label + ": no bounds")
        continue
    if abs(zmin - target) > 0.5:
        shift(a, target - zmin)
        fixed.append({"label": label, "dz": round(target - zmin, 2), "to": target})

saved = unreal.EditorLevelLibrary.save_current_level()

# verify
final, ok_all = [], True
for label, a in by_label.items():
    zmin, zmax = zmin_max(a)
    if label.endswith("_Monitor"):
        target = 75.0
    elif label in lantern_targets:
        target = lantern_targets[label]
    else:
        target = 0.0
    ok = zmin is not None and abs(zmin - target) < 5.0
    ok_all = ok_all and ok
    final.append({"label": label, "z_min": round(zmin, 2) if zmin is not None else None,
                  "target": target, "ok": ok})

__bridge_result__ = {"ok": ok_all and len(errors) == 0 and bool(saved),
    "fixed_count": len(fixed), "fixed": fixed, "errors": errors,
    "final": final, "saved": bool(saved), "level": world.get_path_name()}
"""

out = BRIDGE.execute_python(code)
r = out.get("result") or {}
print("ok:", r.get("ok"), "| saved:", r.get("saved"), "| fixed:", r.get("fixed_count"))
for f in r.get("final", []):
    print(f"  {f['label']:30s} z_min={f['z_min']:>8} target={f['target']:>7} {'OK' if f['ok'] else 'FAIL'}")
for e in r.get("errors", []):
    print("ERROR:", e)
if not r:
    print("raw:", json.dumps(out, default=str)[:700])
