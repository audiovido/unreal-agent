"""FREEBUFF ASSET acceptance: import real category assets into a disposable UE
project (headless Cmd pass). env: ASSETLIB_MARKER, ASSETLIB_IMPORT_SPEC.

spec: [{id, category, file, dest, expect_class}] -> verifies each imported
geometry (class + real bounds cm), collects materials + animation sequences in
the destination folder, saves the level, writes marker, exits.
"""
import json
import os
import sys
import time

import unreal

started = time.time()
marker_path = os.environ.get("ASSETLIB_MARKER", "")
spec_path = os.environ.get("ASSETLIB_IMPORT_SPEC", "")


def log(msg):
    print(f"[{time.time() - started:6.1f}] {msg}", flush=True)


def write_marker(ok, payload):
    payload.update({"ok": bool(ok), "elapsed_seconds": round(time.time() - started, 1),
                    "engine": unreal.SystemLibrary.get_engine_version()})
    if marker_path:
        with open(marker_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, default=str)
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


def verify_asset(asset_path, label):
    asset = unreal.load_asset(asset_path)
    if asset is None:
        return {"label": label, "asset_path": asset_path, "ok": False}
    asset_class = asset.get_class().get_name()
    out = {"label": label, "asset_path": asset_path, "class": asset_class, "ok": True}
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actor = None
    if asset_class == "StaticMesh":
        actor = subsystem.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
        if actor is not None:
            actor.static_mesh_component.set_static_mesh(asset)
            try:
                mats = [str(m.get_path_name()) if m else None
                        for m in asset.get_editor_property("materials")]
                out["materials"] = [m for m in mats if m]
            except Exception as exc:
                out["materials_error"] = str(exc)
    elif asset_class == "SkeletalMesh":
        actor = subsystem.spawn_actor_from_class(unreal.SkeletalMeshActor, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
        if actor is not None:
            actor.skeletal_mesh_component.set_skeletal_mesh_asset(asset)
            try:
                mats = [str(m.get_path_name()) if m else None
                        for m in asset.get_editor_property("materials")]
                out["materials"] = [m for m in mats if m]
            except Exception as exc:
                out["materials_error"] = str(exc)
            skel = asset.get_editor_property("skeleton")
            out["skeleton"] = str(skel.get_path_name()) if skel else None
    if actor is None:
        out.update({"ok": False, "error": f"could not spawn {asset_class}"})
        return out
    origin, extent = actor.get_actor_bounds(False, False)
    out["size_cm"] = [round(extent.x * 2.0, 2), round(extent.y * 2.0, 2), round(extent.z * 2.0, 2)]
    actor.set_actor_label(f"VERIFY_{label}")
    subsystem.destroy_actor(actor)
    return out


def list_sequences(folder):
    found = []
    try:
        assets = unreal.EditorAssetLibrary.list_assets(folder, recursive=True)
        for path in assets:
            asset = unreal.load_asset(path)
            if asset is not None and "AnimSequence" in asset.get_class().get_name():
                found.append(path)
    except Exception as exc:
        log(f"sequence scan issue: {exc}")
    return found


def main():
    payload = {"started_at": started, "assets": []}
    ok = True
    spec = json.loads(open(spec_path, encoding="utf-8").read())
    try:
        level = unreal.EditorLevelLibrary
        try:
            if not level.load_level("/Game/ShowcaseMap"):
                level.new_level("/Game/ShowcaseMap")
        except Exception as exc:
            log(f"level open issue: {exc}")

        for item in spec:
            paths = import_one(item["file"], item["dest"], item["id"])
            if not paths:
                payload["assets"].append({"id": item["id"], "ok": False,
                                          "error": "no imports"})
                ok = False
                continue
            # Primary = first geometry asset (StaticMesh/SkeletalMesh).
            primary = None
            for path in paths:
                asset = unreal.load_asset(path)
                if asset is not None and asset.get_class().get_name() in (
                        "StaticMesh", "SkeletalMesh"):
                    primary = path
                    break
            if primary is None:
                primary = paths[0]
            verified = verify_asset(primary, item["id"])
            expected = item.get("expect_class")
            if expected and verified.get("class") != expected:
                verified["ok"] = False
                verified["expected_class"] = expected
            verified["sequences"] = list_sequences(item["dest"])
            payload["assets"].append({**verified, "category": item["category"]})
            ok = ok and bool(verified.get("ok"))

        level.save_current_level()
        unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
        log("map + packages saved")
    except Exception as exc:
        payload["fatal"] = f"{type(exc).__name__}: {exc}"
        ok = False
    write_marker(ok, payload)


main()
