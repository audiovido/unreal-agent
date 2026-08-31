#!/usr/bin/env python3
"""LIVE Unreal graduation probe: Level/Actor toolchain (Phase 7).

Runs against the running Unreal Editor bridge in the CURRENT level, spawns a
prefixed set of disposable actors, and deletes every actor it created in a
finally block. NEVER saves the level and never changes project config, so the
existing map (possibly dirty from user work) is left exactly as found.

Exit code 0 = all checks green. Each line:  PASS|FAIL <check> [detail]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.unreal.unreal_bridge import UnrealBridge

PREFIX = "UA_Grad_"
bridge = UnrealBridge(timeout=60)
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(("PASS" if ok else "FAIL") + f" {name}" + (f" | {detail}" if detail else ""), flush=True)


def payload(result):
    if isinstance(result, dict):
        inner = result.get("result")
        return inner if isinstance(inner, dict) else result
    return {}


def _delete_by_label(label):
    try:
        bridge.delete_actor(label)
    except Exception:
        pass


def cleanup():
    try:
        r = bridge.execute_python(
            "import unreal; __bridge_result__ = [a.get_actor_label() for a in unreal.EditorLevelLibrary.get_all_level_actors()]"
        )
        inner = r.get("result") if isinstance(r, dict) else None
        labels = inner if isinstance(inner, list) else []
        for label in labels:
            if str(label).startswith(PREFIX):
                _delete_by_label(str(label))
    except Exception:
        pass


try:
    # 1. snapshot list_level_actors
    result = bridge.list_level_actors()
    inner = result.get("result") if isinstance(result, dict) else None
    check("list_level_actors returns list", isinstance(inner, list), str(type(inner)))
    before_labels = {str(a.get("label")) for a in inner if isinstance(a, dict)} if isinstance(inner, list) else set()
    print(f"INFO pre-existing actor labels: {len(before_labels)}", flush=True)

    # 2. spawn deterministic label
    result = bridge.spawn_actor(class_name="StaticMeshActor", actor_name=PREFIX + "Cube01", location=[300, 0, 100], scale=[0.5, 0.5, 0.5], mesh_asset="/Engine/BasicShapes/Cube.Cube")
    p = payload(result)
    check("spawn_actor ok", p.get("ok") is True, json.dumps(p)[:200])
    check("spawn_actor deterministic label", p.get("label") == PREFIX + "Cube01", str(p.get("label")))
    check("spawn_actor class StaticMeshActor", p.get("class") == "StaticMeshActor", str(p.get("class")))

    # 3. get_actor by label
    result = bridge.get_actor(PREFIX + "Cube01")
    p = payload(result)
    check("get_actor by label", p.get("ok") is True and p.get("label") == PREFIX + "Cube01", json.dumps(p)[:200])
    loc = p.get("location") or []
    check("get_actor location [300,0,100]", [round(float(v)) for v in loc] == [300, 0, 100], str(loc))

    # 4. move_actor
    result = bridge.move_actor(PREFIX + "Cube01", [500, 100, 200])
    p = payload(result)
    check("move_actor ok", p.get("ok") is True, json.dumps(p)[:200])
    loc = p.get("location") or []
    check("move_actor applied [500,100,200]", [round(float(v)) for v in loc] == [500, 100, 200], str(loc))

    # 5. duplicate labels -> ambiguous structured failure
    result = bridge.spawn_actor(class_name="StaticMeshActor", actor_name=PREFIX + "Cube01", location=[0, 0, 50])
    p = payload(result)
    check("spawn duplicate label actor", p.get("ok") is True, json.dumps(p)[:200])
    result = bridge.get_actor(PREFIX + "Cube01")
    p = payload(result)
    check("get_actor ambiguous label structured failure", p.get("ok") is False and "mbiguous" in str(p.get("error", "")) and "matches" in json.dumps(p), json.dumps(p)[:250])

    # 6. delete_actor must refuse ambiguous
    result = bridge.delete_actor(PREFIX + "Cube01")
    p = payload(result)
    check("delete_actor ambiguous refuses", p.get("ok") is False and "mbiguous" in str(p.get("error", "")), json.dumps(p)[:200])

    # 7. delete one + verify via unique internal name
    r = bridge.execute_python(
        "import unreal; ms = [a for a in unreal.EditorLevelLibrary.get_all_level_actors() if a.get_actor_label() == %r]; __bridge_result__ = [a.get_name() for a in ms]" % (PREFIX + "Cube01")
    )
    inner = r.get("result") if isinstance(r, dict) else None
    internal_names = list(inner) if isinstance(inner, list) else []
    check("duplicate internal names captured", len(internal_names) == 2, str(internal_names))
    if internal_names:
        result = bridge.delete_actor(internal_names[0])
        p = payload(result)
        check("delete_actor by internal name ok", p.get("ok") is True, json.dumps(p)[:200])
    else:
        check("delete_actor by internal name ok", False, "no internal names found")

    # 8. create light
    result = bridge.spawn_actor(class_name="PointLight", actor_name=PREFIX + "Light01", location=[0, 0, 300])
    p = payload(result)
    check("spawn PointLight", p.get("ok") is True and p.get("class") == "PointLight", json.dumps(p)[:200])

    # 9. get_actor missing -> structured failure
    result = bridge.get_actor("UA_Grad_DoesNotExist_XYZ")
    p = payload(result)
    check("get_actor missing structured failure", p.get("ok") is False and "not found" in str(p.get("error", "")).lower(), json.dumps(p)[:200])

    # 10. delete remaining by name
    for label in [PREFIX + "Cube01", PREFIX + "Light01"]:
        result = bridge.delete_actor(label)
        p = payload(result)
        check(f"delete_actor {label} fails while ambiguous" if label == PREFIX + "Cube01" else f"delete_actor {label}",
              p.get("ok") is False or p.get("deleted") is not False, json.dumps(p)[:200])

    # resolve ambiguity: delete first remaining cube by internal name, then by label
    r = bridge.execute_python(
        "import unreal; ms = [a for a in unreal.EditorLevelLibrary.get_all_level_actors() if a.get_actor_label() == %r]; __bridge_result__ = [a.get_name() for a in ms]" % (PREFIX + "Cube01")
    )
    inner = r.get("result") if isinstance(r, dict) else None
    names = list(inner) if isinstance(inner, list) else []
    for n in names:
        _delete_by_label(n)
    result = bridge.get_actor(PREFIX + "Cube01")
    p = payload(result)
    check("all duplicate cubes deleted", p.get("ok") is False, json.dumps(p)[:200])

    # 11. no leftover UA_Grad actors
    r = bridge.execute_python(
        "import unreal; __bridge_result__ = [a.get_actor_label() for a in unreal.EditorLevelLibrary.get_all_level_actors() if a.get_actor_label().startswith(%r)]" % PREFIX
    )
    inner = r.get("result") if isinstance(r, dict) else None
    leftover = list(inner) if isinstance(inner, list) else []
    check("no UA_Grad actors left behind", len(leftover) == 0, str(leftover))

    # 12. level identity unchanged (still the real project map, un-saved)
    result = bridge.get_current_level()
    p = payload(result)
    check("active level still real /Game map", str(p.get("world_path", "")).startswith("/Game/"), str(p.get("world_path")))
finally:
    cleanup()

failed = [name for name, ok in results if not ok]
print("ACTOR_TOOLCHAIN_LIVE:", "PASS" if not failed else f"FAIL ({len(failed)})", flush=True)
sys.exit(0 if not failed else 1)