#!/usr/bin/env python3
"""LIVE Unreal graduation probe: Blueprint toolchain (Phase 6).

Runs against the running Unreal Editor bridge. Uses a DISPOSABLE package
folder /Game/_UA_Grad/ inside the current project and deletes it afterwards.
Never touches the active map, never saves it, never changes project config.

Exit code 0 = all checks green. Each line:  PASS|FAIL <check> [detail]
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

FOLDER = "/Game/_UA_Grad"
BP_PATH = f"{FOLDER}/BP_GradProbe"

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


def cleanup():
    try:
        bridge.delete_asset(BP_PATH)
    except Exception:
        pass
    try:
        bridge.execute_python(
            "import unreal; unreal.EditorAssetLibrary.delete_directory(%r)" % FOLDER
        )
    except Exception:
        pass


try:
    # 1. create Blueprint
    r = bridge.execute_python(
        "import unreal; unreal.EditorAssetLibrary.make_directory(%r)" % FOLDER
    )
    r = bridge.execute_python(
        "assets = unreal.EditorAssetLibrary.list_assets(%r); __bridge_result__ = {'ok': True, 'assets': [str(a) for a in assets]}" % FOLDER
    )
    bt = __import__("tools.unreal.blueprint_tools", fromlist=["BlueprintTools"]).BlueprintTools(bridge)
    result = bt.create_blueprint(BP_PATH, parent_class="Actor")
    p = payload(result)
    check("create_blueprint returns ok", p.get("ok") is True, json.dumps(p)[:200])
    check("create_blueprint class is Blueprint", p.get("class") == "Blueprint", str(p.get("class")))

    # 2. inspect Blueprint
    result = bt.inspect_blueprint(BP_PATH)
    p = payload(result)
    check("inspect_blueprint ok", p.get("ok") is True, json.dumps(p)[:200])
    check("inspect_blueprint resolves object path", str(p.get("asset_path", "")).endswith("BP_GradProbe"), str(p.get("asset_path")))

    # 3. add variable
    result = bt.add_blueprint_variable(BP_PATH, "GradMarker", "String")
    p = payload(result)
    check("add_blueprint_variable String GradMarker", p.get("ok") is True, json.dumps(p)[:300])

    # 4. set default WRONG_VALUE
    result = bt.set_blueprint_variable_default(BP_PATH, "GradMarker", "WRONG_VALUE")
    p = payload(result)
    check("set_blueprint_variable_default WRONG_VALUE", p.get("ok") is True, json.dumps(p)[:200])

    # 5. read back
    result = bt.get_blueprint_variable_default(BP_PATH, "GradMarker")
    p = payload(result)
    check("get_blueprint_variable_default reads WRONG_VALUE", p.get("value") == "WRONG_VALUE", str(p.get("value")))

    # 6. compile + save + reload verify (the full tool)
    result = bt.compile_blueprint(BP_PATH)
    p = payload(result)
    check("compile_blueprint verified BS_UP_TO_DATE", p.get("verified") is True, json.dumps(p)[:300])
    check("compile_blueprint saved", p.get("save_ok") is True)

    # 7. persisted value survives reload
    result = bt.get_blueprint_variable_default(BP_PATH, "GradMarker")
    p = payload(result)
    check("value persists across reload", p.get("value") == "WRONG_VALUE", str(p.get("value")))

    # 8. change to EXPECTED_VALUE + save_blueprint + re-read
    result = bt.set_blueprint_variable_default(BP_PATH, "GradMarker", "EXPECTED_VALUE")
    p = payload(result)
    check("set EXPECTED_VALUE", p.get("ok") is True, json.dumps(p)[:200])
    result = bt.save_blueprint(BP_PATH)
    p = payload(result)
    check("save_blueprint ok", p.get("ok") is True and p.get("saved") is True, json.dumps(p)[:200])
    result = bt.get_blueprint_variable_default(BP_PATH, "GradMarker")
    p = payload(result)
    check("EXPECTED_VALUE persists after save+reload", p.get("value") == "EXPECTED_VALUE", str(p.get("value")))

    # 9. missing Blueprint -> structured failure
    result = bt.get_blueprint_variable_default("/Game/_UA_Grad/BP_DoesNotExist", "X")
    p = payload(result)
    check("missing blueprint structured failure", p.get("ok") is False and "not found" in str(p.get("error", "")).lower(), json.dumps(p)[:200])

    # 10. wrong asset type (level path passed to compile_blueprint) no TypeError
    result = bt.compile_blueprint("/Game/Maps/AvaLive_Main")
    p = payload(result)
    check("level-as-blueprint structured INVALID_BLUEPRINT_PATH",
          p.get("code") == "INVALID_BLUEPRINT_PATH" and p.get("ok") is False, json.dumps(p)[:200])
    result = bt.compile_blueprint(12345)
    check("non-string asset path structured failure", isinstance(result, dict) and result.get("ok") is False, str(result)[:200])

    # 11. delete + verify absence
    result = bridge.delete_asset(BP_PATH)
    p = payload(result)
    check("delete_asset ok", p.get("ok") is True or p.get("deleted") is True, json.dumps(p)[:200])
    result = bridge.get_asset_info(BP_PATH)
    p = payload(result)
    check("deleted blueprint absent", p.get("ok") is False, json.dumps(p)[:200])
finally:
    cleanup()

failed = [name for name, ok in results if not ok]
print("BLUEPRINT_TOOLCHAIN_LIVE:", "PASS" if not failed else f"FAIL ({len(failed)})", flush=True)
sys.exit(0 if not failed else 1)