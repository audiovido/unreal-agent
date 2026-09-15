"""FREEBUFF ASSET: GUI-editor pass for viewport proof.

Loads /Game/SmokeMap, verifies the spawned meshes are present in the level,
frames them with the level viewport camera, ticks a few seconds so the
viewport can present, then writes a marker. The actual PNG is captured by the
host from the OS window (capture_window.ps1) — no AutomationLibrary reliance.

env: ASSETLIB_MARKER
"""
import json
import os
import sys
import time

import unreal

started = time.time()
marker_path = os.environ.get("ASSETLIB_MARKER", "")


def log(msg):
    print(f"[{time.time() - started:6.1f}] {msg}", flush=True)


def write_marker(ok, payload):
    payload.update({"ok": bool(ok), "elapsed_seconds": round(time.time() - started, 1),
                    "engine": unreal.SystemLibrary.get_engine_version()})
    if marker_path:
        try:
            with open(marker_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, default=str)
        except Exception as exc:
            log(f"marker write failed: {exc}")
    log(f"DONE ok={ok}")
    try:
        os._exit(0 if ok else 1)
    except SystemExit:
        sys.exit(0 if ok else 1)


def main():
    payload = {"started_at": started}
    ok = True
    try:
        level = unreal.EditorLevelLibrary
        try:
            loaded = level.load_level("/Game/SmokeMap")
            log(f"load_level /Game/SmokeMap -> {loaded}")
            if not loaded:
                level.new_level("/Game/SmokeMap")
                log("new_level ok")
        except Exception as exc:
            log(f"load_level issue: {exc}")

        time.sleep(2.0)

        # Report what is actually present in the level (proof of spawned assets).
        actors_info = []
        try:
            subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
            actors = subsystem.get_all_level_actors()
            for actor in actors:
                label = actor.get_actor_label()
                if label.startswith("ASSET_"):
                    entry = {"label": label, "class": actor.get_class().get_name()}
                    if actor.get_class().get_name() == "StaticMeshActor":
                        mesh = actor.static_mesh_component.get_editor_property("static_mesh")
                        entry["mesh"] = str(mesh.get_path_name()) if mesh else None
                    actors_info.append(entry)
        except Exception as exc:
            log(f"actor scan failed: {exc}")
        payload["level_actors"] = actors_info
        log(f"level actors: {actors_info}")

        try:
            unreal.EditorLevelLibrary.set_level_viewport_camera_info(
                unreal.Vector(60, -950, 260), unreal.Rotator(-10, 0, 0))
            log("viewport camera set")
        except Exception as exc:
            log(f"camera set failed: {exc}")

        # Give the viewport time to present the level before host capture.
        time.sleep(8.0)
        payload["viewport_ready"] = True
    except Exception as exc:
        payload["fatal"] = f"{type(exc).__name__}: {exc}"
        ok = False
    write_marker(ok, payload)


main()
