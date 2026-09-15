#!/usr/bin/env python3
"""LIVE Unreal graduation probe: Save/Map management (Phase 8 + BUG 2 fix).

Must run against the DISPOSABLE project's freshly opened Untitled level.
Verifies Save-As derives from the LIVE project name (generic), never a
hardcoded AvaLive path; dirty flags; package existence; startup map; a second
map; and map switching/read-back. Leaves the disposable project with two real
saved maps; no other project is touched.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.unreal.unreal_bridge import UnrealBridge

bridge = UnrealBridge(timeout=90)
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(("PASS" if ok else "FAIL") + f" {name}" + (f" | {detail}" if detail else ""), flush=True)


def payload(result):
    if isinstance(result, dict):
        inner = result.get("result")
        return inner if isinstance(inner, dict) else result
    return {}


try:
    ident = payload(bridge.get_project_identity())
    project_name = ident.get("project_name") or ""
    check("probe runs in disposable project", project_name.startswith("UA_GradAudit_"), project_name)

    # Remove any leftover disposable probe actors from previous runs so the
    # ambiguity checks stay deterministic (disposable project only).
    r = bridge.execute_python(
        "import unreal; ms = [a for a in unreal.EditorLevelLibrary.get_all_level_actors() if a.get_actor_label().startswith('SaveProbe')]; __bridge_result__ = [a.get_name() for a in ms]"
    )
    inner = r.get("result") if isinstance(r, dict) else None
    for name in list(inner) if isinstance(inner, list) else []:
        try:
            bridge.delete_actor(str(name))
        except Exception:
            pass

    # 1. temp level present (informational: only the first run starts Untitled;
    # re-runs begin on the already saved map)
    cur = payload(bridge.get_current_level())
    before_path = str(cur.get("world_path", ""))
    was_temp = before_path.startswith("/Temp/") or "/Untitled_" in before_path
    print(("INFO first-run temp Untitled level" if was_temp else "INFO re-run on saved map") + " | " + before_path, flush=True)

    # 2. save_level on temp -> Save-As generic /Game/Maps/<project>
    result = bridge.save_level()
    p = payload(result)
    expected_prefix = "/Game/Maps/" + project_name
    check("save_level verified", p.get("verified") is True, json.dumps(p)[:300])
    check("save_level package exists", p.get("package_exists") is True)
    check("dirty_after is False", p.get("dirty_after") is False, str(p.get("dirty_after")))
    check("no AvaLive default leaked", "AvaLive" not in json.dumps(p), json.dumps(p)[:250])
    check("map_after under /Game/", str(p.get("map_after", "")).startswith("/Game/"), str(p.get("map_after")))
    check("saved_map follows /Game/Maps/<project>", str(p.get("saved_map", "")).startswith(expected_prefix), str(p.get("saved_map")))
    check("startup map persisted", p.get("startup_map_persisted") is True, str(p.get("startup_map")))
    saved_map = (p.get("saved_map") or "").split(".")[0]

    # 3. dirty after save actually false on second read
    dirty = payload(bridge.is_level_dirty())
    check("is_level_dirty False after save", dirty.get("is_dirty") is False, json.dumps(dirty)[:200])

    # 4. active map identity correct
    cur = payload(bridge.get_current_level())
    check("active map identity = saved map", str(cur.get("world_path", "")).startswith(saved_map + "."), str(cur.get("world_path")))

    # 5. startup map file check from disk
    cfg = Path(ident.get("project_path", "")).parent / "Config" / "DefaultEngine.ini"
    cfg_text = cfg.read_text(encoding="utf-8") if cfg.exists() else ""
    check("DefaultEngine.ini EditorStartupMap updated", f"EditorStartupMap={saved_map}" in cfg_text, saved_map)

    # 6. spawn + dirty + save again (dirty_before True, dirty_after False)
    result = bridge.spawn_actor(class_name="StaticMeshActor", actor_name="SaveProbeCube", location=[100, 0, 0], scale=[0.5, 0.5, 0.5], mesh_asset="/Engine/BasicShapes/Cube.Cube")
    p = payload(result)
    check("spawn SaveProbeCube", p.get("ok") is True, json.dumps(p)[:150])
    dirty = payload(bridge.is_level_dirty())
    check("dirty True after spawn", dirty.get("is_dirty") is True, json.dumps(dirty)[:150])
    result = bridge.save_level()
    p = payload(result)
    check("save after spawn verified + clean", p.get("verified") is True and p.get("dirty_after") is False, json.dumps(p)[:250])
    r = bridge.get_actor("SaveProbeCube")
    check("actor persists after save", payload(r).get("ok") is True, json.dumps(payload(r))[:150])

    # 7. second real map (per-run unique name so re-runs always create fresh)
    alt_map = "/Game/Maps/" + project_name + "_Alt" + time.strftime("%H%M%S")
    result = bridge.create_default_level(alt_map)
    p = payload(result)
    check("create_default_level ok", p.get("ok") is True, json.dumps(p)[:250])
    cur = payload(bridge.get_current_level())
    check("active map switched to alt", str(cur.get("world_path", "")).startswith(alt_map + "."), str(cur.get("world_path")))
    result = bridge.save_level()
    p = payload(result)
    check("alt map save verified", p.get("verified") is True, json.dumps(p)[:250])

    # 8. switch back to first map + read-back (UE 5.8 API: LevelEditorSubsystem.load_level)
    r = bridge.execute_python(
        "import unreal; s = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem); ok = bool(s.load_level(%r)); __bridge_result__ = {'ok': ok}" % saved_map
    )
    check("load_level back to first map", payload(r).get("ok") is True, json.dumps(payload(r))[:150])
    cur = payload(bridge.get_current_level())
    check("read-back first map identity", str(cur.get("world_path", "")).startswith(saved_map + "."), str(cur.get("world_path")))
    r = bridge.get_actor("SaveProbeCube")
    check("SaveProbeCube still there after reload", payload(r).get("ok") is True, json.dumps(payload(r))[:150])

    # 9. both maps exist as assets (object-path form, no .umap suffix)
    r = bridge.list_assets("/Game/Maps", recursive=True)
    inner = r.get("result") if isinstance(r, dict) else {}
    assets = [str(a) for a in inner.get("assets", [])] if isinstance(inner, dict) else []
    maps = [a for a in assets if a.startswith("/Game/Maps/" + project_name)]
    check("both maps exist as real assets", len(maps) >= 2, str(sorted(maps)))
finally:
    pass

failed = [name for name, ok in results if not ok]
print("SAVE_MAP_TOOLCHAIN_LIVE:", "PASS" if not failed else f"FAIL ({len(failed)})", flush=True)
sys.exit(0 if not failed else 1)