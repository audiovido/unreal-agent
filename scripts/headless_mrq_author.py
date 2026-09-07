"""headless_mrq_author.py — author the isolated assets needed for a HEADLESS
(command-line) Movie Render Queue render of the durable Aivido cast.

Everything lives in /Game/CineMRQ/ (fully isolated). The certified
/Game/Maps/AividoHQ map is NEVER saved; it is only duplicated into
/Game/CineMRQ/RenderMap so the headless render has its own map copy with the
durable 8/8 cast + a bound CineCamera. After authoring, the live editor is
returned to the certified AividoHQ map.

Assets created (all under /Game/CineMRQ/):
  * RenderMap        — duplicate of certified AividoHQ + MRQ_Cam (saved)
  * MRQ_CastHero     — LevelSequence, 30 fps, playback 0..8 s, camera cut
                       bound to MRQ_Cam (saved)
  * MRQ_Config       — MoviePipelinePrimaryConfig: 1920x1080 PNG frames to
                       an absolute output dir (saved)
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.unreal.unreal_bridge import UnrealBridge

ASSET_ROOT = "/Game/CineMRQ"
SRC_MAP = "/Game/Maps/AividoHQ"
RENDER_MAP = ASSET_ROOT + "/RenderMap"
SEQ_ASSET = ASSET_ROOT + "/MRQ_CastHero"
CFG_ASSET = ASSET_ROOT + "/MRQ_Config"
CAM_LABEL = "MRQ_Cam"
HERO_LABEL = "AVIDO_Human_Master"
FRAMES_DIR = (r"C:/Users/Shadow/Desktop/Unreal-Agent/cinematic-v2/"
              r"reports/cinematic/headless_mrq/frames").replace("\\", "/")

_CODE = r'''
import unreal
import json

def j(v):
    return json.dumps(v)

out = {}

ed = unreal.EditorActorSubsystem()
before_actors = len(ed.get_all_level_actors())
before_cast = [a.get_actor_label() for a in ed.get_all_level_actors()
               if (a.get_actor_label() or "").startswith("AVIDO_Human_")]
out["certified_before"] = {"actor_count": before_actors,
                           "cast": sorted(before_cast)}

tools = unreal.AssetToolsHelpers.get_asset_tools()

unreal.EditorAssetLibrary.make_directory(__ROOT__)
if unreal.EditorAssetLibrary.does_asset_exist(__RMAP__):
    unreal.EditorAssetLibrary.delete_asset(__RMAP__)
dup = unreal.EditorAssetLibrary.duplicate_asset(__SMAP__, __RMAP__)
out["render_map_duplicate"] = {"ok": dup is not None,
                               "path": __RMAP__ if dup else None}

les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
les.load_level(__RMAP__)
ed = unreal.EditorActorSubsystem()
actors = ed.get_all_level_actors()
cast = [a.get_actor_label() for a in actors
        if (a.get_actor_label() or "").startswith("AVIDO_Human_")]
hero = None
for a in actors:
    if (a.get_actor_label() or "") == __HERO__:
        hero = a
        break
out["render_map_loaded"] = {"actor_count": len(actors), "cast": sorted(cast),
                            "hero_present": hero is not None}
if hero is None:
    out["ok"] = False
    out["error"] = "Master not found in render map"
    __bridge_result__ = out
else:
    hloc = hero.get_actor_location()
    bb = hero.get_actor_bounds(False)
    zmin = bb[0].z - bb[1].z
    zmax = bb[0].z + bb[1].z
    out["hero"] = {"loc": [round(hloc.x, 1), round(hloc.y, 1), round(hloc.z, 1)],
                   "zmin": round(zmin, 2), "zmax": round(zmax, 2)}

    cam_loc = unreal.Vector(hloc.x - 360.0, hloc.y, hloc.z + 132.0)
    cam_rot = unreal.Rotator(pitch=5.0, yaw=0.0, roll=0.0)
    cam = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.CineCameraActor, cam_loc, cam_rot)
    cam.set_actor_label(__CAM__)
    cc = cam.get_component_by_class(unreal.CineCameraComponent)
    if cc is not None:
        try:
            cc.set_editor_property("current_fov", 50.0)
        except Exception as exc:
            out["cam_fov_error"] = str(exc)[:120]
    out["camera"] = {"label": __CAM__,
                     "loc": [round(cam_loc.x, 1), round(cam_loc.y, 1),
                             round(cam_loc.z, 1)],
                     "rot": [cam_rot.pitch, cam_rot.yaw, cam_rot.roll]}

    saved_level = bool(unreal.EditorLoadingAndSavingUtils.save_current_level())
    out["render_map_saved"] = saved_level

    seq = tools.create_asset("MRQ_CastHero", __ROOT__,
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
        out["sequence"] = {"ok": seq_ok and saved_seq,
                           "camera_bound": bound, "saved": saved_seq}
        try:
            out["sequence_range"] = [
                float(unreal.MovieSceneSequenceExtensions.get_playback_range_start_seconds(seq)),
                float(unreal.MovieSceneSequenceExtensions.get_playback_range_end_seconds(seq)),
            ]
        except Exception:
            pass
    else:
        out["sequence"] = {"ok": False, "error": "sequence create failed"}

    cfg = None
    try:
        cfg = tools.create_asset("MRQ_Config", __ROOT__,
                                 unreal.MoviePipelinePrimaryConfig, None)
    except Exception as exc:
        out["config_create_error"] = str(exc)[:160]
    cfg_ok = cfg is not None
    if cfg_ok:
        try:
            oset = cfg.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
            oset.set_editor_property("output_resolution", unreal.IntPoint(1920, 1080))
            oset.set_editor_property("output_directory", unreal.DirectoryPath(__FRAMES__))
            oset.set_editor_property("file_name_format", "frame_{frame_number}")
            oset.set_editor_property("zero_pad_frame_numbers", 4)
            oset.set_editor_property("override_existing_output", True)
            pout = cfg.find_or_add_setting_by_class(
                unreal.MoviePipelineImageSequenceOutput_PNG)
        except Exception as exc:
            out["config_setting_error"] = str(exc)[:160]
        saved_cfg = bool(unreal.EditorAssetLibrary.save_loaded_asset(cfg, False))
        out["config"] = {"ok": saved_cfg, "saved": saved_cfg}
    else:
        out["config"] = {"ok": False, "error": "config asset create failed"}

    les.load_level(__SMAP__)
    ed = unreal.EditorActorSubsystem()
    out["certified_after"] = {"actor_count": len(ed.get_all_level_actors())}
    out["ok"] = bool(out.get("render_map_saved")
                     and out.get("sequence", {}).get("ok")
                     and out.get("config", {}).get("ok"))
    __bridge_result__ = out
'''


def _build() -> str:
    return (_CODE
            .replace("__ROOT__", json.dumps(ASSET_ROOT))
            .replace("__RMAP__", json.dumps(RENDER_MAP))
            .replace("__SMAP__", json.dumps(SRC_MAP))
            .replace("__SEQ__", json.dumps(SEQ_ASSET))
            .replace("__CFG__", json.dumps(CFG_ASSET))
            .replace("__CAM__", json.dumps(CAM_LABEL))
            .replace("__HERO__", json.dumps(HERO_LABEL))
            .replace("__FRAMES__", json.dumps(FRAMES_DIR)))


def main() -> None:
    bridge = UnrealBridge(timeout=180)
    res = bridge.execute_python(_build())
    print(json.dumps(res, indent=2, default=str))


if __name__ == "__main__":
    main()