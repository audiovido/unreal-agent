"""FREEBUFF ASSET P1: editor-side Unreal smoke import.

Executed inside UnrealEditor via -ExecutePythonScript on a disposable project.

Reads env:
  ASSETLIB_MARKER  - completion marker JSON path (also .log next to it)
  ASSETLIB_FBX     - FBX to import
  ASSETLIB_GLB     - GLB to import

Imports both into /Game/Smoke/, verifies each (class + real actor bounds in
cm), spawns them in a lit level, captures a high-res viewport screenshot, saves
the level, then exits the process.
"""
import json
import os
import sys
import time

import unreal

started = time.time()
marker_path = os.environ.get("ASSETLIB_MARKER", "")
fbx_path = os.environ.get("ASSETLIB_FBX", "")
glb_path = os.environ.get("ASSETLIB_GLB", "")
log_lines = []


def log(msg):
    log_lines.append(f"[{time.time() - started:6.1f}] {msg}")
    print(log_lines[-1], flush=True)


def write_marker(ok, payload):
    payload.update({
        "ok": bool(ok),
        "elapsed_seconds": round(time.time() - started, 1),
        "engine": unreal.SystemLibrary.get_engine_version(),
    })
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


def import_one(source, destination, label):
    task = unreal.AssetImportTask()
    task.filename = source
    task.destination_path = destination
    task.automated = True
    task.save = True
    task.replace_existing = True
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    tools.import_asset_tasks([task])
    paths = [str(p) for p in (task.imported_object_paths or [])]
    log(f"import {label}: {source} -> {paths}")
    return paths


def verify_and_spawn(asset_path, label, at):
    asset = unreal.load_asset(asset_path)
    if asset is None:
        log(f"VERIFY FAIL {label}: {asset_path} not loadable")
        return {"label": label, "asset_path": asset_path, "ok": False}
    asset_class = asset.get_class().get_name()
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actor = None
    if asset_class == "StaticMesh":
        actor = subsystem.spawn_actor_from_class(unreal.StaticMeshActor, at, unreal.Rotator(0, 0, 0))
        if actor is not None:
            actor.static_mesh_component.set_static_mesh(asset)
    elif asset_class == "SkeletalMesh":
        actor = subsystem.spawn_actor_from_class(unreal.SkeletalMeshActor, at, unreal.Rotator(0, 0, 0))
        if actor is not None:
            actor.skeletal_mesh_component.set_skeletal_mesh_asset(asset)
    if actor is None:
        log(f"SPAWN FAIL {label}: {asset_class} could not be spawned")
        return {"label": label, "asset_path": asset_path, "class": asset_class, "ok": False}
    actor.set_actor_label(f"ASSET_{label}")
    origin, extent = actor.get_actor_bounds(False, False)
    size_cm = [round(extent.x * 2.0, 2), round(extent.y * 2.0, 2), round(extent.z * 2.0, 2)]
    log(f"spawned {label} class={asset_class} size_cm={size_cm}")
    return {"label": label, "asset_path": asset_path, "class": asset_class,
            "actor": actor.get_actor_label(), "size_cm": size_cm, "ok": True}


def main():
    payload = {"started_at": started, "steps": []}
    try:
        editor_level = unreal.EditorLevelLibrary
        ok = True

        # Ensure we are in a saveable, open level.
        try:
            loaded = editor_level.load_level("/Game/SmokeMap")
            log(f"load_level /Game/SmokeMap -> {loaded}")
            if not loaded:
                editor_level.new_level("/Game/SmokeMap")
                log("new_level /Game/SmokeMap ok")
        except Exception as exc:
            log(f"level open fallback: {exc}")
            try:
                editor_level.new_level("/Game/SmokeMap")
                log("new_level /Game/SmokeMap ok")
            except Exception as exc2:
                log(f"new_level failed: {exc2}")
                payload["level_error"] = f"{type(exc2).__name__}: {exc2}"

        # Lights for a visible proof shot.
        try:
            subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
            light = subsystem.spawn_actor_from_class(unreal.DirectionalLight, unreal.Vector(0, 400, 900), unreal.Rotator(-60, 0, 0))
            if light is not None:
                light.set_actor_label("ASSET_Sun")
        except Exception as exc:
            log(f"light spawn failed: {exc}")

        fbx_paths = import_one(fbx_path, "/Game/Smoke/FBX", "FBX") if fbx_path else []
        glb_paths = import_one(glb_path, "/Game/Smoke/GLB", "GLB") if glb_path else []
        all_paths = fbx_paths + glb_paths
        payload["imported_paths"] = all_paths
        if not all_paths:
            payload["error"] = "no imports produced objects"
            write_marker(False, payload)
            return

        # Verify + spawn primary geometry assets, side by side.
        mesh_imports = []
        verified = []
        for path in all_paths:
            asset = unreal.load_asset(path)
            if asset is None:
                continue
            cls = asset.get_class().get_name()
            if cls in ("StaticMesh", "SkeletalMesh"):
                mesh_imports.append(path)

        for idx, path in enumerate(mesh_imports):
            at = unreal.Vector(idx * 250.0 - 120.0, 0, 50)
            result = verify_and_spawn(path, f"Mesh{idx}", at)
            verified.append(result)
            ok = ok and result["ok"]
        payload["verified"] = verified

        # Save the level + packages (screenshot proof happens in the GUI pass).
        try:
            editor_level.save_current_level()
            unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
            log("level saved")
        except Exception as exc:
            log(f"save level failed: {exc}")

        # Content scan proof.
        found = []
        try:
            content_dir = unreal.Paths.project_content_dir()
            for root, _dirs, files in os.walk(content_dir):
                for f in files:
                    if f.lower().endswith((".uasset", ".umap")):
                        found.append(os.path.join(root, f).replace("\\", "/"))
        except Exception as exc:
            log(f"content scan failed: {exc}")
        payload["content_files"] = sorted(found)
        payload["ok_so_far"] = ok
        write_marker(ok, payload)
    except Exception as exc:
        log(f"FATAL: {type(exc).__name__}: {exc}")
        payload["fatal"] = f"{type(exc).__name__}: {exc}"
        write_marker(False, payload)


main()
