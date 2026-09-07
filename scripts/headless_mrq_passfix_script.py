"""headless_mrq_passfix_script.py - ENGINE-SIDE (run via -ExecutePythonScript)

The MRQ_Config already has OutputSetting (1920x1080 PNG) + PNG image output,
but is missing a RENDER PASS -> "Shot has 0 Passes". This adds the concrete
MoviePipelineDeferredPassBase pass, saves, and verifies it persists (not nulled).

Writes reports/cinematic/headless_mrq/passfix_result.json.
"""
import json
import os

import unreal

RESULTS = {"phase": "started", "actions": [], "error": None, "ok": False}


def log(msg: str) -> None:
    print(f"[MRQ_PASSFIX] {msg}")
    RESULTS["actions"].append(msg)


def main() -> None:
    log("STARTED")

    config = unreal.load_asset("/Game/CineMRQ/MRQ_Config")
    if config is None:
        RESULTS["error"] = "MRQ_Config not found"
        log("ERROR: config not found")
        _finish()
        return

    log("config methods w/ 'set': " + str(sorted(m for m in dir(config) if "set" in m.lower())))

    pass_cls = unreal.MoviePipelineDeferredPassBase
    try:
        RESULTS["pass_abstract"] = bool(pass_cls.is_abstract())
        log(f"DeferredPassBase abstract? {RESULTS['pass_abstract']}")
    except Exception as exc:
        RESULTS["pass_abstract"] = None
        log(f"WARN is_abstract failed: {exc}")

    added = config.find_or_add_setting_by_class(pass_cls)
    log(f"Added pass object: {added} class={added.get_class().get_name() if added else None}")
    RESULTS["pass_added"] = added.get_class().get_name() if added else None

    saved = bool(unreal.EditorAssetLibrary.save_loaded_asset(config, False))
    log(f"Saved config: {saved}")
    RESULTS["saved"] = saved

    reloaded = unreal.load_asset("/Game/CineMRQ/MRQ_Config")
    log("reloaded methods w/ 'set': " + str(sorted(m for m in dir(reloaded) if "set" in m.lower())))

    # Verify persistence by reflecting for a settings getter.
    pass_count = 0
    null_count = 0
    getter = None
    for cand in ("get_settings", "get_all_settings", "find_settings"):
        if hasattr(reloaded, cand):
            getter = cand
            break
    if getter:
        try:
            items = getattr(reloaded, getter)()
            for it in items:
                if it is None:
                    null_count += 1
                else:
                    cn = it.get_class().get_name()
                    log(f"  persisted setting: {cn}")
                    if "DeferredPass" in cn or "MoviePipelineRenderPass" in cn:
                        pass_count += 1
            RESULTS["setting_count"] = len(items)
            RESULTS["null_settings"] = null_count
            RESULTS["render_pass_persisted"] = pass_count
            log(f"total={len(items)} nulls={null_count} render_passes={pass_count}")
        except Exception as exc:
            log(f"WARN getter {getter} failed: {exc}")
    else:
        log("WARN no settings getter found")

    RESULTS["ok"] = bool(saved) and pass_count >= 1 and null_count == 0
    RESULTS["phase"] = "done"
    _finish()


def _finish() -> None:
    out_path = os.path.abspath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "reports", "cinematic",
        "headless_mrq", "passfix_result.json"))
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(RESULTS, fh, indent=2, default=str)
    log(f"Wrote {out_path}")


main()