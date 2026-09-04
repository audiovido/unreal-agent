#!/usr/bin/env python3
"""LIVE Unreal graduation probe: UI detector end-to-end (Phase UI).

Runs against the live Unreal Editor bridge and validates the committed
generic UI-panel detector (core.visual_acceptance.find_ui_bbox) on a real
session, using only committed machinery:

  1. live session check (ping + project identity + map)
  2. create a REAL persisted WidgetBlueprint via the committed
     BlueprintTools.create_umg_widget tool (compile + save + reload-verify)
  3. capture the live editor viewport and the PIE GameViewport, run the
     committed detector on the real frames: a real scene with no panel must
     NEVER earn the UI/readability bonus (the structural-gate honesty
     contract that this graduation pins)
  4. PIE lifecycle: begin play -> GameViewport capture -> end play
  5. cleanup: widget asset removed, no residue in the project

BLOCKED sub-check (recorded, not a failure): injecting a real UMG overlay
panel into the captured frame for a positive pixel-level detection.  UE 5.8
exposes no widget-tree editing surface to Python (WidgetBlueprint.widget_tree
and WidgetTree.root_widget are hidden, WidgetBlueprintLibrary and
Actor.add_component are absent), and the native viewport capture does not
include UMG overlays.  The positive panel contract is therefore pinned by the
hermetic synthetic suite (tests/test_ui_detection_structure.py draws the exact
2D dark-slab semantics UMG produces on the frame).

Evidence is written to assetlib/proof/golden_live/.  The probe never touches
user project source: only the standard Saved/UnrealAgent capture dir and one
uniquely-named disposable widget under /Game/ReleaseMissions.

Exit codes: 0 = PASS (all verifiable checks green), 1 = FAIL, 2 = BLOCKED
(no live session).
"""
from __future__ import annotations

import json
import shutil
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.unreal.blueprint_tools import BlueprintTools
from tools.unreal.unreal_bridge import UnrealBridge
from core.visual_acceptance import measure, score

RESULTS: list[dict] = []


def check(name: str, status: str, detail: str = "") -> None:
    RESULTS.append({"name": name, "ok": status == "PASS",
                    "status": status, "detail": detail})
    print(f"{status} {name}" + (f" | {detail}" if detail else ""), flush=True)


def payload(result) -> dict:
    if isinstance(result, dict):
        inner = result.get("result")
        return inner if isinstance(inner, dict) else result
    return {}


def main() -> int:
    EVIDENCE_DIR = ROOT / "assetlib" / "proof" / "golden_live"
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    bridge = UnrealBridge(timeout=60)
    wname = f"UA_Det_Grad_{uuid.uuid4().hex[:6]}"
    wpath = f"/Game/ReleaseMissions/{wname}"
    try:
        ping = bridge.ping()
        if not ping.get("ok"):
            print("UI_DETECTOR_GRADUATION_LIVE: BLOCKED (no live editor session)")
            return 2
        check("live bridge ping", "PASS", str(ping.get("message")))

        ident = payload(bridge.get_project_identity())
        project = ident.get("project_name") or "?"
        world = payload(bridge.get_current_level())
        map_name = world.get("world_name") or "?"
        print(f"session: project={project} map={map_name} "
              f"engine={ping.get('engine', '?')}", flush=True)

        # ---- real persisted WidgetBlueprint (committed tool) ---------------
        wb_result = BlueprintTools(bridge).create_umg_widget(wpath)
        wb_inner = payload(wb_result)
        check("real UMG widget asset created+compiled+saved+verified",
              "PASS" if bool(wb_inner.get("ok")) else "FAIL",
              json.dumps({"path": wpath, "compiled": wb_inner.get("compiled"),
                          "saved": wb_inner.get("saved"),
                          "verified": wb_inner.get("verified")}))

        # ---- live editor frame: real scene must not score as UI ------------
        cap = bridge.capture_unreal_viewport()
        cap_info = payload(cap)
        if cap_info.get("ok") and cap_info.get("path") \
                and Path(cap_info["path"]).is_file():
            dst = EVIDENCE_DIR / "live_editor_frame.png"
            shutil.copyfile(cap_info["path"], dst)
            m = measure(str(dst))
            s = score(m)
            honest = m.ui_bbox is None and s.ui <= 2.0 and s.readability <= 2.0
            check("real editor frame: scene without panel earns no UI bonus",
                  "PASS" if honest else "FAIL",
                  f"bbox={m.ui_bbox} ui={s.ui:.2f} readability="
                  f"{s.readability:.2f} overall={s.overall:.2f}")
        else:
            check("real editor frame: scene without panel earns no UI bonus",
                  "FAIL", "no usable viewport capture")

        # ---- PIE lifecycle + GameViewport capture --------------------------
        payload(bridge.execute_python("""
subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
subsystem.editor_request_begin_play()
__bridge_result__ = {"ok": True}
"""))
        time.sleep(4.0)
        pie = payload(bridge.execute_python("""
subsystem = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
game_world = subsystem.get_game_world()
__bridge_result__ = {"ok": game_world is not None,
                     "world": game_world.get_name() if game_world else None}
"""))
        check("PIE started (game world live)", "PASS" if pie.get("ok") else "FAIL",
              str(pie.get("world")))
        cap2 = bridge.capture_pie_viewport()
        cap2_info = payload(cap2)
        pie_ok = bool(cap2_info.get("ok")) and cap2_info.get("path") \
            and Path(cap2_info["path"]).is_file()
        if pie_ok:
            dst2 = EVIDENCE_DIR / "live_pie_frame.png"
            shutil.copyfile(cap2_info["path"], dst2)
            m2 = measure(str(dst2))
            s2 = score(m2)
            honest2 = m2.ui_bbox is None and s2.ui <= 2.0
            check("PIE GameViewport capture ok + detector honest on it",
                  "PASS" if honest2 else "FAIL",
                  f"source_game_viewport={cap2_info.get('source_is_game_viewport')} "
                  f"bbox={m2.ui_bbox} ui={s2.ui:.2f} overall={s2.overall:.2f}")
        else:
            check("PIE GameViewport capture ok + detector honest on it",
                  "FAIL", json.dumps(cap2_info)[:200])

        # ---- BLOCKED sub-check (engine API limitation, documented) ---------
        check("UMG overlay panel pixels in captured frame (positive case)",
              "BLOCKED",
              "UE 5.8 Python exposes no widget-tree/component-creation API "
              "(widget_tree/root_widget hidden, no WidgetBlueprintLibrary, no "
              "Actor.add_component) and the native viewport capture excludes "
              "UMG overlays; positive panel contract pinned by hermetic suite")

        # ---- cleanup --------------------------------------------------------
        payload(bridge.execute_python("""
subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
subsystem.editor_request_end_play()
__bridge_result__ = {"ok": True}
"""))
        time.sleep(2.0)
        cleanup = payload(bridge.execute_python(
            "import unreal\n"
            f"path = {wpath!r}\n"
            "asset = unreal.EditorAssetLibrary.load_asset(path)\n"
            "if asset is not None:\n"
            "    unreal.EditorAssetLibrary.delete_asset(path)\n"
            "unreal.EditorAssetLibrary.save_directory('/Game/ReleaseMissions')\n"
            "__bridge_result__ = {'ok': True, 'deleted': asset is not None}\n"))
        gone = payload(bridge.execute_python(
            "import unreal\n"
            f"gone = unreal.EditorAssetLibrary.load_asset({wpath!r}) is None\n"
            "__bridge_result__ = {'ok': True, 'gone': gone}\n"))
        check("cleanup: PIE ended + widget asset removed",
              "PASS" if cleanup.get("ok") and gone.get("gone") else "FAIL",
              f"deleted={cleanup.get('deleted')} gone={gone.get('gone')}")

        failures = [r for r in RESULTS if r["status"] == "FAIL"]
        blocked = [r for r in RESULTS if r["status"] == "BLOCKED"]
        verdict = "PASS" if not failures else "FAIL"
        evidence = {
            "task": "AIVIDO_UI_DETECTOR_GRADUATION_LIVE",
            "status": verdict,
            "date": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "session": {"project": project, "map": map_name,
                        "engine": ping.get("engine", "?")},
            "widget_asset": wpath,
            "checks": RESULTS,
            "blocked_notes": [r["detail"] for r in blocked],
            "evidence": {
                "editor_frame": str(EVIDENCE_DIR / "live_editor_frame.png"),
                "pie_frame": str(EVIDENCE_DIR / "live_pie_frame.png"),
            },
        }
        (EVIDENCE_DIR / "live_ui_detector_graduation.json").write_text(
            json.dumps(evidence, indent=2), encoding="utf-8")
        print(json.dumps(evidence, indent=2))
        print(f"UI_DETECTOR_GRADUATION_LIVE: {verdict}"
              + (f" ({len(blocked)} blocked sub-check)" if blocked else ""))
        return 0 if verdict == "PASS" else 1
    except Exception as exc:
        # best-effort cleanup on crash
        try:
            payload(bridge.execute_python("""
subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
subsystem.editor_request_end_play()
__bridge_result__ = {"ok": True}
"""))
        except Exception:
            pass
        print(f"UI_DETECTOR_GRADUATION_LIVE: ERROR "
              f"{type(exc).__name__}: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())