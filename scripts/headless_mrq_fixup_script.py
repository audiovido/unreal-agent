"""headless_mrq_fixup_script.py — ENGINE-SIDE fixup for the authored assets:
set the MRQ_Cam CineCamera field of view and the sequence playback range with
the correct UE 5.8 python names (the first author pass used names that do not
exist on 5.8: 'current_fov' and 'set_playback_range_start_seconds').

Run inside UnrealEditor-Cmd with -ExecutePythonScript (headless, -NullRHI).
Writes reports/cinematic/headless_mrq/fixup_result.json.
"""
import json
import os

import unreal

RENDER_MAP = "/Game/CineMRQ/RenderMap"
SEQ_ASSET = "/Game/CineMRQ/MRQ_CastHero"
CAM_LABEL = "MRQ_Cam"
RESULT = r"C:/Users/Shadow/Desktop/Unreal-Agent/cinematic-v2/reports/cinematic/headless_mrq/fixup_result.json"

out = {}


def _write():
    try:
        with open(RESULT, "w") as f:
            json.dump(out, f, indent=2, default=str)
    except Exception as exc:
        unreal.log_error("MRQ_FIXUP result write failed: " + repr(exc))


def main():
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    les.load_level(RENDER_MAP)

    # ---- camera FOV ------------------------------------------------------
    cam = None
    for a in unreal.EditorActorSubsystem().get_all_level_actors():
        if (a.get_actor_label() or "") == CAM_LABEL:
            cam = a
            break
    if cam is not None:
        cc = cam.get_component_by_class(unreal.CineCameraComponent)
        if cc is not None:
            props = sorted(p for p in dir(cc)
                           if any(k in p.lower() for k in ("fov", "field", "focal")))
            out["camera_candidates"] = props
            chosen = None
            for p in ("current_fov", "field_of_view", "fov", "current_focal_length"):
                if p in props:
                    chosen = p
                    break
            if chosen:
                if "focal" in chosen:
                    cc.set_editor_property(chosen, 40.0)
                else:
                    cc.set_editor_property(chosen, 50.0)
                out["camera_fov_set"] = {"property": chosen,
                                         "value": cc.get_editor_property(chosen)}
            out["render_map_saved"] = bool(
                unreal.EditorLoadingAndSavingUtils.save_current_level())
    else:
        out["camera_found"] = False

    # ---- sequence playback range -----------------------------------------
    seq = unreal.EditorAssetLibrary.load_asset(SEQ_ASSET)
    if seq is not None:
        out["seq_methods"] = sorted(
            m for m in dir(unreal.MovieSceneSequenceExtensions)
            if "playback" in m.lower() or "display_rate" in m.lower()
            or "tick_resolution" in m.lower())
        try:
            unreal.MovieSceneSequenceExtensions.set_display_rate(
                seq, unreal.FrameRate(30, 1))
            out["display_rate"] = str(
                unreal.MovieSceneSequenceExtensions.get_display_rate(seq))
        except Exception as exc:
            out["display_rate_error"] = str(exc)[:160]
        # Correct UE 5.8 API: set_playback_start_seconds / set_playback_end_seconds.
        applied = None
        try:
            unreal.MovieSceneSequenceExtensions.set_playback_start_seconds(seq, 0.0)
            unreal.MovieSceneSequenceExtensions.set_playback_end_seconds(seq, 8.0)
            applied = "set_playback_start/end_seconds"
        except Exception as exc:
            out["range_error"] = str(exc)[:160]
        out["range_setter_applied"] = applied
        try:
            out["playback_start_s"] = float(
                unreal.MovieSceneSequenceExtensions.get_playback_start_seconds(seq))
            out["playback_end_s"] = float(
                unreal.MovieSceneSequenceExtensions.get_playback_end_seconds(seq))
        except Exception as exc:
            out["range_read_error"] = str(exc)[:160]
        saved_seq = bool(unreal.EditorAssetLibrary.save_loaded_asset(seq, False))
        out["sequence_saved"] = saved_seq
    else:
        out["sequence_found"] = False

    out["ok"] = bool(out.get("render_map_saved") and out.get("sequence_saved"))
    _write()


try:
    main()
except Exception as _exc:
    import traceback
    out["fatal"] = traceback.format_exc()
    _write()
    unreal.log_error("MRQ_FIXUP_FATAL " + repr(_exc))

unreal.SystemLibrary.execute_console_command(None, "QuitEditor")