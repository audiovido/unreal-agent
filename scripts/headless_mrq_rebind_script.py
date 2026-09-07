"""headless_mrq_rebind_script.py — ENGINE-SIDE fixup: rebind the sequence's
camera-cut possessable to MRQ_Cam in the RENDER MAP package context.

When the sequence was authored it possessed MRQ_Cam while the CERTIFIED map
was loaded (later Saved-As to /Game/CineMRQ/RenderMap). The possessable
binding therefore points at /Game/Maps/AividoHQ...:PersistentLevel.MRQ_Cam,
which does not resolve when Movie Render Queue loads /Game/CineMRQ/RenderMap
(headless -game) -> "No camera actor found on Eval Tick: 0". Re-possessing the
actor in the RenderMap context stores the matching package path.

Run inside UnrealEditor-Cmd with -ExecutePythonScript (headless, -NullRHI).
Writes reports/cinematic/headless_mrq/rebind_result.json.
"""
import json
import os

import unreal

RENDER_MAP = "/Game/CineMRQ/RenderMap"
SEQ_ASSET = "/Game/CineMRQ/MRQ_CastHero"
CAM_LABEL = "MRQ_Cam"
RESULT = r"C:/Users/Shadow/Desktop/Unreal-Agent/cinematic-v2/reports/cinematic/headless_mrq/rebind_result.json"

out = {}


def _write():
    try:
        with open(RESULT, "w") as f:
            json.dump(out, f, indent=2, default=str)
    except Exception as exc:
        unreal.log_error("MRQ_REBIND result write failed: " + repr(exc))


def main():
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    les.load_level(RENDER_MAP)
    out["loaded_map"] = RENDER_MAP

    cam = None
    for a in unreal.EditorActorSubsystem().get_all_level_actors():
        if (a.get_actor_label() or "") == CAM_LABEL:
            cam = a
            break
    out["camera_found"] = cam is not None
    if cam is None:
        out["ok"] = False
        out["error"] = "MRQ_Cam not found in RenderMap"
        _write()
        return
    out["camera_path"] = cam.get_path_name()

    seq = unreal.EditorAssetLibrary.load_asset(SEQ_ASSET)
    if seq is None:
        out["ok"] = False
        out["error"] = "sequence not found"
        _write()
        return

    cut_track = None
    try:
        tracks = unreal.MovieSceneSequenceExtensions.find_tracks_by_type(
            seq, unreal.MovieSceneCameraCutTrack)
        cut_track = tracks[0] if tracks else None
    except Exception as exc:
        out["find_track_error"] = str(exc)[:160]
    if cut_track is None:
        cut_track = unreal.MovieSceneSequenceExtensions.add_track(
            seq, unreal.MovieSceneCameraCutTrack)
        section = unreal.MovieSceneTrackExtensions.add_section(cut_track)
        unreal.MovieSceneSectionExtensions.set_range_seconds(section, 0.0, 8.0)
    else:
        sections = unreal.MovieSceneTrackExtensions.get_sections(cut_track)
        section = sections[0] if sections else \
            unreal.MovieSceneTrackExtensions.add_section(cut_track)

    bound = False
    binding_path = None
    try:
        proxy = unreal.MovieSceneSequenceExtensions.add_possessable(seq, cam)
        bid = unreal.MovieSceneSequenceExtensions.get_binding_id(seq, proxy)
        section.set_camera_binding_id(bid)
        bound = True
        binding_path = str(cam.get_path_name())
    except Exception as exc:
        out["bind_error"] = str(exc)[:200]

    try:
        section_range = [
            float(unreal.MovieSceneSectionExtensions.get_start_frame_seconds(section)),
            float(unreal.MovieSceneSectionExtensions.get_end_frame_seconds(section)),
        ]
        out["section_range"] = section_range
    except Exception as exc:
        out["section_range_error"] = str(exc)[:120]

    saved_seq = bool(unreal.EditorAssetLibrary.save_loaded_asset(seq, False))
    out["sequence_saved"] = saved_seq
    out["camera_bound"] = bound
    out["binding_path"] = binding_path
    out["ok"] = bool(bound and saved_seq)
    _write()


try:
    main()
except Exception as _exc:
    import traceback
    out["fatal"] = traceback.format_exc()
    _write()
    unreal.log_error("MRQ_REBIND_FATAL " + repr(_exc))

unreal.SystemLibrary.execute_console_command(None, "QuitEditor")