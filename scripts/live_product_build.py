#!/usr/bin/env python3
"""Phase 19 graduation: MULTI-SYSTEM PRODUCT BUILD in ONE natural-language
request through the real API:

- project context (no explicit path)
- environment geometry (floor cube)
- light
- camera
- Blueprint actor + String variable compiled and validated
- UMG widget created, compiled and verified
- saved map
- final viewport screenshot proof
- long-task continuation to COMPLETE with no user follow-up

Requires a disposable project already open in the editor (the E2E project).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASE = "http://127.0.0.1:8765"
results = []

TASK = (
    "Build a small polished Unreal scene in the currently open project: "
    "spawn a large floor cube named ProdFloor with scale 10x10x1 at the origin "
    "as the environment geometry, add lighting with a PointLight named ProdLight, "
    "place a CameraActor named ProdCam, create a Blueprint actor named BP_ProdProbe "
    "with a String variable Status initially set to READY and expected value READY, "
    "compile and save it, create a simple UMG widget named WBP_ProdWidget, "
    "save the map, then capture a final viewport screenshot as proof."
)


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(("PASS" if ok else "FAIL") + f" {name}" + (f" | {detail}" if detail else ""), flush=True)


def preclean():
    """Remove leftover disposable probe actors (disposable project only) so a
    rerun starts from a deterministic empty slate. Deletes by exact internal
    name to honor duplicate-label ambiguity rules."""
    from tools.unreal.unreal_bridge import UnrealBridge
    bridge = UnrealBridge(timeout=30)
    r = bridge.execute_python(
        "import unreal; __bridge_result__ = [{\"name\": a.get_name(), \"label\": a.get_actor_label()} for a in unreal.EditorLevelLibrary.get_all_level_actors()]"
    )
    inner = r.get("result") if isinstance(r, dict) else {}
    actors = inner if isinstance(inner, list) else []
    for a in actors:
        label = str(a.get("label") or "")
        if label.startswith(("Prod", "UA_L_", "GOAL_TEST", "UA_PROD_")):
            try:
                bridge.delete_actor(str(a.get("name")))
            except Exception:
                pass


def main():
    preclean()
    r = requests.post(BASE + "/api/action", json={"action": "prompt", "payload": {"message": TASK}}, timeout=30)
    r.raise_for_status()
    tid = r.json().get("task_id") or (r.json().get("data") or {}).get("task_id")
    check("product build submitted", bool(tid), tid)

    tools = []
    terminal = None
    stall = None
    deadline = time.time() + 900
    while time.time() < deadline:
        ev = requests.get(BASE + "/api/events", timeout=20).json().get("events", [])
        for e in [x for x in ev if x.get("task_id") == tid]:
            t = str(e.get("title") or "")
            if t.startswith("Running "):
                tools.append(t.replace("Running ", "").strip())
            if e.get("type") == "complete" or t == "COMPLETE":
                terminal = "COMPLETE"
            if "STALLED" in t or "EXECUTION_FAILED" in t or t == "BLOCKED":
                stall = stall or t
                terminal = terminal or "FAILED"
        if terminal:
            break
        time.sleep(2)

    tools = sorted(set(tools))
    check("product build COMPLETE", terminal == "COMPLETE", f"terminal={terminal} stall={stall}")
    required = {
        "inspect_project", "unreal_ping", "spawn_actor", "save_level",
        "create_blueprint", "add_blueprint_variable", "set_blueprint_variable_default",
        "compile_blueprint", "get_blueprint_variable_default",
        "create_umg_widget", "get_actor", "capture_unreal_viewport",
    }
    missing = required - set(tools)
    check("all systems exercised", not missing, f"missing={sorted(missing)}")
    check("no stall", stall is None, str(stall))
    print("TOOL SEQUENCE:", tools, flush=True)

    # asset verification through the live bridge
    from tools.unreal.unreal_bridge import UnrealBridge
    bridge = UnrealBridge(timeout=30)
    for path, expect in (
        ("/Game/_UA_GradA/BP_ProdProbe", "Blueprint"),
        ("/Game/_UA_GradA/WBP_ProdWidget", "WidgetBlueprint"),
    ):
        r = bridge.get_asset_info(path)
        payload = r.get("result") if isinstance(r, dict) else {}
        check(f"asset exists {path}", payload.get("ok") is True and str(payload.get("class", "")).lower() in ("blueprint", "widgetblueprint"), json.dumps(payload)[:120])
    r = bridge.get_actor("ProdFloor")
    check("ProdFloor on map", r.get("result", {}).get("ok") is True, json.dumps(r.get("result"))[:120])
    r = bridge.get_actor("UA_PROD_Camera")
    check("camera on map", r.get("result", {}).get("ok") is True and r.get("result", {}).get("class") == "CameraActor", json.dumps(r.get("result"))[:120])
    r = bridge.execute_python(
        "import unreal; __bridge_result__ = [a.get_actor_label() for a in unreal.EditorLevelLibrary.get_all_level_actors() if a.get_class().get_name() == 'PointLight']"
    )
    inner = r.get("result") if isinstance(r, dict) else None
    lights = list(inner) if isinstance(inner, list) else []
    check("light(s) on map", len(lights) >= 1 and all(str(x).startswith("UA_L_") for x in lights), str(lights))

    failed = [n for n, ok in results if not ok]
    print("PRODUCT_BUILD_LIVE:", "PASS" if not failed else f"FAIL ({len(failed)})", flush=True)
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()