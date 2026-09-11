"""FREEBUFF ASSET acceptance: build the showcase scene (GUI pass).

Loads /Game/ShowcaseMap, spawns a ground plane + sun, places each imported
real asset (display scale + grounding via real bounds), then walks a pose
list writing pose_<idx>.ready markers so the host can capture each viewport.
Final done marker carries placed-asset evidence. env: ASSETLIB_MARKER,
ASSETLIB_POSES_JSON, ASSETLIB_ASSETS_JSON.
"""
import json
import math
import os
import sys
import time

import unreal

print("SHOWCASE_SCRIPT_START", flush=True)
started = time.time()
marker_path = os.environ.get("ASSETLIB_MARKER", "")
poses_json = os.environ.get("ASSETLIB_POSES_JSON", "")
assets_json = os.environ.get("ASSETLIB_ASSETS_JSON", "")
poses_dir = os.path.dirname(marker_path)


def log(msg):
    print(f"[{time.time() - started:6.1f}] {msg}", flush=True)


def write_marker(ok, payload):
    payload.update({"ok": bool(ok), "elapsed_seconds": round(time.time() - started, 1),
                    "engine": unreal.SystemLibrary.get_engine_version()})
    with open(marker_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)
    log(f"DONE ok={ok}")
    try:
        os._exit(0 if ok else 1)
    except SystemExit:
        sys.exit(0 if ok else 1)


def spawn_static(asset_path, label, at):
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    asset = unreal.load_asset(asset_path)
    if asset is None or asset.get_class().get_name() != "StaticMesh":
        return None, "asset not static mesh"
    actor = subsystem.spawn_actor_from_class(unreal.StaticMeshActor, at, unreal.Rotator(0, 0, 0))
    if actor is None:
        return None, "spawn failed"
    actor.static_mesh_component.set_static_mesh(asset)
    actor.set_actor_label(label)
    return actor, None


def spawn_skeletal(asset_path, label, at):
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    asset = unreal.load_asset(asset_path)
    if asset is None or asset.get_class().get_name() != "SkeletalMesh":
        return None, "asset not skeletal mesh"
    actor = subsystem.spawn_actor_from_class(unreal.SkeletalMeshActor, at, unreal.Rotator(0, 0, 0))
    if actor is None:
        return None, "spawn failed"
    actor.skeletal_mesh_component.set_skeletal_mesh_asset(asset)
    actor.set_actor_label(label)
    return actor, None


def ground_actor(actor, x, y):
    origin, extent = actor.get_actor_bounds(False, False)
    # bottom of the world-space AABB -> sit on ground plane at z=0
    bottom = origin.z - extent.z
    actor.set_actor_location(unreal.Vector(x, y, -bottom), False, False)
    return origin, extent


def frame_camera(center, radius, extra_z=0.55):
    dist = max(radius * 1.7, 200.0)
    loc = unreal.Vector(center.x, center.y - dist, center.z + radius * extra_z)
    pitch = -math.degrees(math.atan2(radius * extra_z, dist))
    unreal.EditorLevelLibrary.set_level_viewport_camera_info(
        loc, unreal.Rotator(pitch=pitch, yaw=0, roll=0))
    return loc


def main():
    ok = True
    payload = {"started_at": started, "placed": [], "poses": []}
    assets = json.loads(open(assets_json, encoding="utf-8").read())
    poses = json.loads(open(poses_json, encoding="utf-8").read())
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    try:
        # NLP-route leg: Blender-processed black SUV (FBX) — import once, idempotent.
        nlr_fbx = "C:/Users/Shadow/Desktop/Unreal-Agent/assetlib/tests/ue/nlr_in/BlackSUV.fbx"
        try:
            existing = unreal.EditorAssetLibrary.list_assets("/Game/NLR/BlackSUV", recursive=True)
            if not existing and os.path.exists(nlr_fbx):
                task = unreal.AssetImportTask()
                task.filename = nlr_fbx
                task.destination_path = "/Game/NLR/BlackSUV"
                task.automated = True
                task.save = True
                task.replace_existing = False
                unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
                log("NLR black SUV imported")
            else:
                log(f"NLR black SUV present ({len(existing)} assets)")
        except Exception as exc:
            log(f"nlr import issue: {exc}")

        level = unreal.EditorLevelLibrary
        try:
            if not level.load_level("/Game/ShowcaseMap"):
                level.new_level("/Game/ShowcaseMap")
        except Exception as exc:
            log(f"level issue: {exc}")

        # Ground plane from engine BasicShapes.
        plane_asset = unreal.load_asset("/Engine/BasicShapes/BasicShapePlane")
        if plane_asset is not None:
            plane = subsystem.spawn_actor_from_class(unreal.StaticMeshActor,
                                                     unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
            plane.static_mesh_component.set_static_mesh(plane_asset)
            plane.set_actor_label("ACC_Ground")
            plane.set_actor_scale3d(unreal.Vector(160, 160, 1))
        sun = subsystem.spawn_actor_from_class(unreal.DirectionalLight,
                                               unreal.Vector(0, 800, 1600), unreal.Rotator(-55, 0, 25))
        if sun is not None:
            sun.set_actor_label("ACC_Sun")
        sky = subsystem.spawn_actor_from_class(unreal.SkyLight,
                                               unreal.Vector(0, 0, 2000), unreal.Rotator(0, 0, 0))
        if sky is not None:
            sky.set_actor_label("ACC_SkyLight")
            try:
                sky.sky_light_component.set_editor_property("source_type", unreal.SkyLightSourceType.SLS_SPECIFIED_CUBEMAP)
            except Exception:
                pass
        log("ground + lights spawned")

        # Idempotency: drop previously placed ACC_* actors on map reload.
        try:
            for a in subsystem.get_all_level_actors():
                if a.get_actor_label().startswith("ACC_"):
                    subsystem.destroy_actor(a)
        except Exception as exc:
            log(f"cleanup existing actors issue: {exc}")

        # Place each asset (all meshes in its import folder) with display
        # scale + group grounding so multi-mesh assets import fully.
        for idx, item in enumerate(assets):
            x = (idx - (len(assets) - 1) / 2.0) * 900.0
            prefix = f"ACC_{item['id']}"
            scale = float(item.get("display_scale") or 1.0)
            spawned = []
            err = None
            try:
                assets_paths = unreal.EditorAssetLibrary.list_assets(item["spawn_folder"], recursive=True)
            except Exception as exc:
                assets_paths = []
                err = f"folder list: {exc}"
            if item.get("kind") == "SkeletalMesh":
                actor, err2 = spawn_skeletal(item["asset_path"], prefix, unreal.Vector(x, 0, 0))
                if actor is None:
                    err = err or err2
                else:
                    spawned = [actor]
            for apath in assets_paths:
                asset = unreal.load_asset(apath)
                if asset is None or asset.get_class().get_name() != "StaticMesh":
                    continue
                actor, err2 = spawn_static(apath, f"{prefix}_{len(spawned)}", unreal.Vector(x, 0, 0))
                if actor is not None:
                    spawned.append(actor)
                else:
                    err = err or err2
            if not spawned:
                payload["placed"].append({"id": item["id"], "ok": False, "error": err})
                ok = False
                continue
            for actor in spawned:
                actor.set_actor_scale3d(unreal.Vector(scale, scale, scale))
            # group ground: raise every actor so the union bottom sits at z=0
            bottoms = []
            for actor in spawned:
                origin, extent = actor.get_actor_bounds(False, False)
                bottoms.append(origin.z - extent.z)
            lift = -min(bottoms)
            # safety: reject unreasonable lift (signals orientation/pivot issue)
            if abs(lift) > 1e7:
                raise ValueError(f"lift too large: {lift} for {item.get('id')}")
            for actor in spawned:
                loc = actor.get_actor_location()
                actor.set_actor_location(unreal.Vector(x, 0, loc.z + lift), False, False)
            # Evidence: collision config (static) / skeleton (skeletal).
            collision_info, skeleton_info = None, None
            for actor in spawned:
                comp = getattr(actor, "static_mesh_component", None)
                if comp is not None:
                    try:
                        comp.set_collision_enabled(unreal.CollisionEnabled.QUERY_AND_PHYSICS)
                        collision_info = str(comp.collision_enabled)
                    except Exception as exc:
                        collision_info = f"error: {exc}"
                    break
            for actor in spawned:
                comp = getattr(actor, "skeletal_mesh_component", None)
                if comp is not None and comp.get_editor_property("skeletal_mesh_asset") is not None:
                    try:
                        skeleton_info = comp.skeletal_mesh_asset.skeleton.get_path_name()
                    except Exception as exc:
                        skeleton_info = f"error: {exc}"
                    break
            # union display size
            mins = [1e12] * 3; maxs = [-1e12] * 3
            for actor in spawned:
                origin, extent = actor.get_actor_bounds(False, False)
                for i, (oa, ea) in enumerate(zip(
                        (origin.x, origin.y, origin.z),
                        (extent.x, extent.y, extent.z))):
                    mins[i] = min(mins[i], oa - ea)
                    maxs[i] = max(maxs[i], oa + ea)
            size_cm = [round(b - a, 1) for a, b in zip(mins, maxs)]
            payload["placed"].append({
                "id": item["id"], "prefix": prefix, "ok": True,
                "actor_count": len(spawned),
                "spawn_folder": item.get("spawn_folder"),
                "display_scale": scale, "size_cm_display": size_cm,
                "collision": collision_info, "skeleton": skeleton_info,
            })
            log(f"placed {prefix} actors={len(spawned)} scale={scale} size={size_cm}")

        # Class scan of imported content (material/texture/anim evidence).
        class_counts = {}
        try:
            for apath in unreal.EditorAssetLibrary.list_assets("/Game/Showcase", recursive=True):
                asset = unreal.load_asset(apath)
                if asset is not None:
                    cls = asset.get_class().get_name()
                    class_counts[cls] = class_counts.get(cls, 0) + 1
        except Exception as exc:
            log(f"class scan issue: {exc}")
        payload["content_class_counts"] = class_counts
        log(f"content classes: {class_counts}")

        # Pose loop only makes sense with a real viewport (GUI editor).
        no_gui = os.environ.get("ASSETLIB_NO_GUI", "0") == "1"
        if not no_gui:
            time.sleep(15.0)  # first shader warm before overview
        shot_dir = os.path.join(unreal.Paths.project_saved_dir(), "Screenshots")
        try:
            os.makedirs(shot_dir, exist_ok=True)
        except Exception:
            pass
        for pidx, pose in ([] if no_gui else enumerate(poses)):
            pose_id = pose.get("id", "overview")
            pose_entry = {"id": pose_id, "idx": pidx, "ok": False, "shot": None}
            try:
                targets = []
                if pose["kind"] == "overview":
                    actors = [a for a in subsystem.get_all_level_actors()
                              if a.get_actor_label().startswith("ACC_")]
                    xs = []
                    max_extent = 400.0
                    for a in actors:
                        _o, e = a.get_actor_bounds(False, False)
                        xs.append(a.get_actor_location().x)
                        max_extent = max(max_extent, e.x, e.y, e.z)
                    if xs:
                        center = unreal.Vector((min(xs) + max(xs)) / 2.0, 0, 150)
                        span = max(xs) - min(xs)
                    else:
                        center = unreal.Vector(0, 0, 150)
                        span = 0.0
                    radius = max(span / 2.0 + max_extent, 1400.0)
                    frame_camera(center, radius, extra_z=0.7)
                elif pose.get("kind") == "nlr":
                    targets = [a for a in subsystem.get_all_level_actors()
                               if (a.get_actor_label().startswith("ACC_black_suv")
                                   or a.get_actor_label().startswith("ACC_nlr_fox"))]
                else:
                    targets = [a for a in subsystem.get_all_level_actors()
                               if a.get_actor_label().startswith(f"ACC_{pose_id}")]
                if not targets and pose.get("kind") != "overview":
                    log(f"pose target missing {pose_id}")
                    payload["poses"].append({"id": pose_id, "ok": False})
                    ok = False
                    continue
                if targets:
                    mins = [1e12] * 3; maxs = [-1e12] * 3
                    for t in targets:
                        origin, extent = t.get_actor_bounds(False, False)
                        for i, (oa, ea) in enumerate(zip(
                                (origin.x, origin.y, origin.z),
                                (extent.x, extent.y, extent.z))):
                            mins[i] = min(mins[i], oa - ea)
                            maxs[i] = max(maxs[i], oa + ea)
                    center = unreal.Vector((mins[0] + maxs[0]) / 2, (mins[1] + maxs[1]) / 2,
                                           (mins[2] + maxs[2]) / 2)
                    radius = max(maxs[0] - mins[0], maxs[1] - mins[1], maxs[2] - mins[2]) / 2
                    frame_camera(center, radius, extra_z=pose.get("extra_z", 0.6))
                pose_entry["ok"] = True
                if pose.get("anim"):
                    for t in targets:
                        comp = getattr(t, "skeletal_mesh_component", None)
                        if comp is not None:
                            try:
                                comp.set_animation(unreal.load_asset(pose["anim"]))
                                pose_entry["anim_played"] = pose["anim"].rsplit(".", 1)[-1]
                                break
                            except Exception as exc:
                                pose_entry["anim_error"] = str(exc)
                with open(os.path.join(poses_dir, f"pose_{pidx:03d}.ready"), "w") as fh:
                    json.dump({"idx": pidx, "id": pose["id"]}, fh)
                log(f"pose {pose_id} ready")
                # In-editor high-res screenshot (primary evidence source).
                try:
                    shot = os.path.join(shot_dir, f"showcase_{pose_id}.png")
                    if os.path.exists(shot):
                        os.remove(shot)
                    unreal.AutomationLibrary.take_high_res_screenshot(1280, 720, shot)
                    for _ in range(10):
                        if os.path.exists(shot):
                            break
                        time.sleep(1.0)
                    if os.path.exists(shot):
                        pose_entry["shot"] = shot.replace("\\", "/")
                        pose_entry["shot_bytes"] = os.path.getsize(shot)
                        log(f"pose {pose_id} shot ok {pose_entry['shot_bytes']}B")
                except Exception as shot_exc:
                    log(f"pose {pose_id} shot failed: {shot_exc}")
                if pose.get("anim_double") and os.path.exists(
                        os.path.join(shot_dir, f"showcase_{pose_id}.png")):
                    time.sleep(3.0)
                    shot2 = os.path.join(shot_dir, f"showcase_{pose_id}_t2.png")
                    if os.path.exists(shot2):
                        os.remove(shot2)
                    try:
                        unreal.AutomationLibrary.take_high_res_screenshot(1280, 720, shot2)
                        for _ in range(10):
                            if os.path.exists(shot2):
                                break
                            time.sleep(1.0)
                        if os.path.exists(shot2):
                            pose_entry["shot2"] = shot2.replace("\\", "/")
                            pose_entry["shot2_bytes"] = os.path.getsize(shot2)
                            pose_entry["advancing"] = (
                                os.path.getsize(shot2) != pose_entry.get("shot_bytes"))
                            log(f"pose {pose_id} t2 shot {pose_entry['shot2_bytes']}B "
                                f"advancing={pose_entry.get('advancing')}")
                    except Exception as exc:
                        log(f"pose {pose_id} t2 shot failed: {exc}")
                time.sleep(7.0)
            except Exception as exc:
                log(f"pose {pose.get('id')} failed: {exc}")
                ok = False
            finally:
                payload["poses"].append(pose_entry)

        if no_gui:
            payload["mode"] = "place-headless"
        else:
            payload["mode"] = "gui-capture"
        level.save_current_level()
        unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
        log("map saved")
    except Exception as exc:
        payload["fatal"] = f"{type(exc).__name__}: {exc}"
        ok = False
    write_marker(ok, payload)


main()
