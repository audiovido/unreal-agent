"""headless_mrq_config_fix_script.py — ENGINE-SIDE fixup: add a base render
pass to MRQ_Config. The authored config only had the OutputSetting + PNG image
sequence output, so the render reported "Shot has 0 Passes" and wrote nothing.
Adding a render pass (MoviePipelineDeferredPass, with fallbacks) gives MRQ >=1
real render pass so frames are actually produced.

Run inside UnrealEditor-Cmd with -ExecutePythonScript (headless, -NullRHI).
Writes reports/cinematic/headless_mrq/config_fix_result.json.
"""
import json
import os

import unreal

CFG_ASSET = "/Game/CineMRQ/MRQ_Config"
RESULT = r"C:/Users/Shadow/Desktop/Unreal-Agent/cinematic-v2/reports/cinematic/headless_mrq/config_fix_result.json"

out = {}


def _write():
    try:
        with open(RESULT, "w") as f:
            json.dump(out, f, indent=2, default=str)
    except Exception as exc:
        unreal.log_error("MRQ_CFGFIX result write failed: " + repr(exc))


def main():
    cfg = unreal.EditorAssetLibrary.load_asset(CFG_ASSET)
    if cfg is None:
        out["ok"] = False
        out["error"] = "config not found"
        _write()
        return

    candidates = [
        "MoviePipelineDeferredPass",
        "MoviePipelineBasePass",
        "MoviePipelineRenderPass",
        "MoviePipelineImageSequenceOutput_PNG",
    ]
    existing = []
    for name in candidates:
        cls = getattr(unreal, name, None)
        if cls is None:
            continue
        try:
            setting = cfg.find_or_add_setting_by_class(cls)
            existing.append({"class": name, "ok": setting is not None})
        except Exception as exc:
            existing.append({"class": name, "error": str(exc)[:120]})
    out["pass_settings"] = existing

    saved = bool(unreal.EditorAssetLibrary.save_loaded_asset(cfg, False))
    out["config_saved"] = saved
    out["ok"] = saved
    _write()


try:
    main()
except Exception as _exc:
    import traceback
    out["fatal"] = traceback.format_exc()
    _write()
    unreal.log_error("MRQ_CFGFIX_FATAL " + repr(_exc))

unreal.SystemLibrary.execute_console_command(None, "QuitEditor")