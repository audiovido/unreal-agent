"""headless_mrq_author_script.py — ENGINE-SIDE authoring for the headless MRQ
render. Run inside UnrealEditor-Cmd via:

    UnrealEditor-Cmd <Project>.uproject \
        -ExecutePythonScript=".../headless_mrq_author_script.py" \
        -unattended -NoP4 -NoXIM -NullRHI

Approach (crash-proof): load the certified /Game/Maps/AividoHQ map, spawn the
render camera on it, then SAVE-AS the current world to /Game/CineMRQ/RenderMap.
No map is ever duplicated-and-reloaded in one process (that pattern hard-crashes
this engine build) and the certified AividoHQ.umap on disk is never written.

Assets produced (all under /Game/CineMRQ/):
  * RenderMap    — copy of certified AividoHQ + MRQ_Cam (saved via Save-As)
  * MRQ_CastHero — LevelSequence, 30 fps, playback 0..8 s, camera cut bound
                   to MRQ_Cam (saved)
  * MRQ_Config   — MoviePipelinePrimaryConfig: 1920x1080 PNG frames to an
                   absolute output dir (saved)

Writes reports/cinematic/headless_mrq/author_result.json.
"""
import json
import os

import unreal

SRC_MAP = "/Game/Maps/AividoHQ"
ROOT = "/Game/CineMRQ"
RENDER_MAP = ROOT + "/RenderMap"
CAM_LABEL = "MRQ_Cam"
HERO_LABEL = "AVIDO_Human_Master"
FRAMES_DIR = r"C:/Users/Shadow/Desktop/Unreal-Agent/cinematic-v2/reports/cinematic/headless_mrq/frames"
RESULT = r"C:/Users/Shadow/Desktop/Unreal-Agent/cinematic-v2/reports/cinematic/headless_mrq/author_result.json"
STARTED = r"C:/Users/Shadow/Desktop/Unreal-Agent/cinematic-v2/reports/cinematic/headless_mrq/_author_started.txt"

out = {}

try:
    os.makedirs(os.path.dirname(STARTED), exist_ok=True)
    with open(STARTED, "w") as _f:
        _f.write("STARTED\n")
except Exception:
    pass


def _write():
    try:
        os.makedirs(os.path.dirname(RESULT), exist_ok=True)
        with open(RESULT, "w") as f:
            json.dump(out, f, indent=2, default=str)
    except Exception as exc:
        unreal.log_error("MRQ_AUTHOR result write failed: " + repr(exc))


def _log(msg):
    unreal.log("MRQ_AUTHOR: " + msg)


def main():
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    les.load_level(SRC_MAP)

    ed = unreal.EditorActorSubsystem()
    actors = ed.get_all_level_actors()
    cast = sorted(a.get_actor_label() for a in actors
                  if (a.get_actor_label() or "").startswith("AVIDO_Human_"))
    out["certified_loaded"] = {"actor_count": len(actors), "cast": cast}

    hero = None
    for a in actors:
        if (a.get_actor_label() or "") == HERO_LABEL:
            hero = a
            break
    if hero is None:
        out["ok"] = False
        out["error"] = "Master not found in certified map"
        _write()
        return

    hloc = hero.get_actor_location()
    bb = hero.get_actor_bounds(False)
    out["hero"] = {"loc": [round(hloc.x, 1), round(hloc.y, 1), round(hloc.z, 1)],
                   "zmin": round(bb[0].z - bb[1].z, 2),
                   "zmax": round(bb[0].z + bb[1].z, 2)}

    cam_loc = unreal.Vector(hloc.x - 360.0, hloc.y, hloc.z + 132.0)
    cam_rot = unreal.Rotator(pitch=5.0, yaw=0.0, roll=0.0)
    cam = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.CineCameraActor, cam_loc, cam_rot)
    cam.set_actor_label(CAM_LABEL)
    cc = cam.get_component_by_class(unreal.CineCameraComponent)
    if cc is not None:
        try:
            cc.set_editor_property("current_fov", 50.0)
        except Exception as exc:
            out["cam_fov_error"] = str(exc)[:120]
    out["camera"] = {"label": CAM_LABEL,
                     "loc": [round(cam_loc.x, 1), round(cam_loc.y, 1),
                             round(cam_loc.z, 1)],
                     "rot": [cam_rot.pitch, cam_rot.yaw, cam_rot.roll]}

    unreal.EditorAssetLibrary.make_directory(ROOT)
    if unreal.EditorAssetLibrary.does_asset_exist(RENDER_MAP):
        unreal.EditorAssetLibrary.delete_asset(RENDER_MAP)

    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    saved_as = bool(unreal.EditorLoadingAndSavingUtils.save_map(world, RENDER_MAP))
    out["render_map_saved"] = saved_as
    _log("render map saved-as: %s" % saved_as)

    tools = unreal.AssetToolsHelpers.get_asset_tools()
    seq = tools.create_asset("MRQ_CastHero", ROOT,
                             unreal.LevelSequence, unreal.LevelSequenceFactoryNew())
    seq_ok = seq is not None
    if seq_ok:
        try:
            unreal.MovieSceneSequenceExtensions.set_display_rate(
                seq, unreal.FrameRate(30, 1))
        except Exception as exc:
            out["fps_error"] = str(exc)[:120]
        try:
            unreal.MovieSceneSequenceExtensions.set_playback_range_start_seconds(seq, 0.0)
            unreal.MovieSceneSequenceExtensions.set_playback_range_end_seconds(seq, 8.0)
        except Exception as exc:
            out["range_error"] = str(exc)[:120]
        cut_track = unreal.MovieSceneSequenceExtensions.add_track(
            seq, unreal.MovieSceneCameraCutTrack)
        section = unreal.MovieSceneTrackExtensions.add_section(cut_track)
        unreal.MovieSceneSectionExtensions.set_range_seconds(section, 0.0, 8.0)
        bound = False
        try:
            proxy = unreal.MovieSceneSequenceExtensions.add_possessable(seq, cam)
            bid = unreal.MovieSceneSequenceExtensions.get_binding_id(seq, proxy)
            section.set_camera_binding_id(bid)
            bound = True
        except Exception as exc:
            out["bind_error"] = str(exc)[:160]
        saved_seq = bool(unreal.EditorAssetLibrary.save_loaded_asset(seq, False))
        out["sequence"] = {"ok": seq_ok and saved_seq, "camera_bound": bound,
                           "saved": saved_seq}
        try:
            out["sequence_range"] = [
                float(unreal.MovieSceneSequenceExtensions.get_playback_range_start_seconds(seq)),
                float(unreal.MovieSceneSequenceExtensions.get_playback_range_end_seconds(seq)),
            ]
        except Exception:
            pass
        _log("sequence saved: %s camera_bound=%s" % (saved_seq, bound))
    else:
        out["sequence"] = {"ok": False, "error": "sequence create failed"}

    cfg = None
    try:
        cfg = tools.create_asset("MRQ_Config", ROOT,
                                 unreal.MoviePipelinePrimaryConfig, None)
    except Exception as exc:
        out["config_create_error"] = str(exc)[:160]
    if cfg is not None:
        try:
            oset = cfg.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
            oset.set_editor_property("output_resolution", unreal.IntPoint(1920, 1080))
            oset.set_editor_property("output_directory", unreal.DirectoryPath(FRAMES_DIR))
            oset.set_editor_property("file_name_format", "frame_{frame_number}")
            oset.set_editor_property("zero_pad_frame_numbers", 4)
            oset.set_editor_property("override_existing_output", True)
            cfg.find_or_add_setting_by_class(unreal.MoviePipelineImageSequenceOutput_PNG)
        except Exception as exc:
            out["config_setting_error"] = str(exc)[:160]
        saved_cfg = bool(unreal.EditorAssetLibrary.save_loaded_asset(cfg, False))
        out["config"] = {"ok": saved_cfg, "saved": saved_cfg}
        _log("config saved: %s" % saved_cfg)
    else:
        out["config"] = {"ok": False, "error": "config asset create failed"}

    out["ok"] = bool(out.get("render_map_saved")
                     and out.get("sequence", {}).get("ok")
                     and out.get("config", {}).get("ok"))
    _log("done ok=%s" % out["ok"])
    _write()


try:
    main()
except Exception as _exc:
    import traceback
    out["fatal"] = traceback.format_exc()
    _write()
    unreal.log_error("MRQ_AUTHOR_FATAL " + repr(_exc))

unreal.SystemLibrary.execute_console_command(None, "QuitEditor")