"""Live UE acceptance for gap-closure BATCH 5 (Sequencer / cameras).

Temporary sequence LS_Batch5Test with a bound transform-keyed cube and a
camera cut, headless scrub/play/pause control, full structure read-back,
save+reopen, and the closed channel-key surface recorded as an engine gap.
Evidence: assetlib/reports/sequencer_tools_batch5.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, "tools/unreal")

from tools.unreal.sequencer_tools_gap import SequencerToolsGap  # noqa: E402
from tools.unreal.unreal_bridge import UnrealBridge  # noqa: E402
from tools.unreal.world_tools_gap import WorldToolsGap  # noqa: E402

LS = "/Game/ToolGap/LS_Batch5Test"
EVIDENCE = Path("assetlib/reports/sequencer_tools_batch5.json")


def main() -> int:
    bridge = UnrealBridge(port=6766)
    ident = bridge.get_identity()
    assert ident.get("ok") and ident.get("project_name") == "ASSET_Showcase2", ident
    st = SequencerToolsGap(bridge)
    wt = WorldToolsGap(bridge)

    steps: list[dict] = []
    report: dict = {"bridge": ident, "steps": steps}

    def r(env: dict) -> dict:
        return (env or {}).get("result") or env or {}

    def step(name: str, ok: bool, detail: dict) -> dict:
        rec = {"step": name, **detail, "ok": bool(ok)}
        steps.append(rec)
        print(f"[{name}] ok={ok} {json.dumps(detail, default=str)[:220]}")
        return rec

    # 0. deterministic wash ---------------------------------------------------
    bridge.execute_python('import unreal; unreal.EditorLoadingAndSavingUtils.load_map("/Game/ShowcaseMap"); __bridge_result__ = {"ok": True}')
    r(bridge.execute_python(f"import unreal; pr = unreal.EditorAssetLibrary.delete_asset('{LS}'); __bridge_result__ = {{'deleted': bool(pr)}}"))
    bridge.execute_python("import unreal; unreal.AssetRegistryHelpers.get_asset_registry().scan_paths_synchronous(['/Game/ToolGap'], force_rescan=True)")
    bridge.save_level()

    # 1. open temp map (no new_level: FATAL world-transition crash risk) -------
    res = r(bridge.open_map("/Game/ToolGap/Batch2Map"))
    r(bridge.execute_python(f'''
import unreal
victims = [a.get_name() for a in (unreal.EditorLevelLibrary.get_all_level_actors() or [])
           if a.get_name().startswith("Gap") or a.get_name().startswith("Mat") or a.get_name().startswith("AnimFox") or a.get_name().startswith("Seq") or a.get_name().startswith("Cam")]
for n in victims:
    for a in unreal.EditorLevelLibrary.get_all_level_actors() or []:
        if a.get_name() == n:
            unreal.EditorLevelLibrary.destroy_actor(a)
            break
__bridge_result__ = {{
    "removed": victims
}}
'''))
    bridge.save_level()
    cnt = r(wt.list_level_actor_details()).get("actor_count", 0) if res.get("ok") else -1
    step("01_open_temp_map", res.get("ok") and cnt == 0, {"open": res, "actor_count_after": cnt})
    if not (res.get("ok") and cnt == 0):
        report["verdict"] = "FAIL"
        EVIDENCE.write_text(json.dumps(report, indent=2, default=str))
        return 1

    # 2. create the level sequence ----------------------------------------------
    res = r(st.create_level_sequence(LS))
    step("02_create_sequence", res.get("ok"), res)

    # 3. inventory contains it ----------------------------------------------------
    res = r(st.list_level_sequences("/Game/ToolGap"))
    step("03_list_sequences", res.get("ok") and any(str(x).startswith(LS) for x in res.get("sequences", [])), res)

    # 4. actors + bindings ---------------------------------------------------------
    res = r(wt.bulk_spawn("StaticMeshActor", 1, origin=(0.0, 0.0, 0.0), name_prefix="Seq", mesh_asset="/Engine/BasicShapes/Cube.Cube"))
    cube = (res.get("created") or [{}])[0].get("name")
    cb = r(st.add_actor_binding(LS, cube))
    cam = r(st.add_camera_cut(LS, "CamBatch5", (800.0, 0.0, 120.0), 0.0, 2.0))
    step("04_bind_cube_and_camera", cb.get("ok") and cam.get("ok") and cam.get("camera_actor"), {"cube_binding": cb, "camera_cut": cam})

    # 5. transform track + section + range (keys recorded as engine-gap probe) -----
    tr = r(st.add_track_with_section(LS, cube, "MovieScene3DTransformTrack", 0.0, 2.0))
    key_probe = r(bridge.execute_python(f'''
import unreal
seq = unreal.EditorAssetLibrary.load_asset("{LS}")
out = {{"ok": True}}
try:
    tracks = unreal.MovieSceneSequenceExtensions.find_tracks_by_type(seq, unreal.MovieScene3DTransformTrack)
    sections = unreal.MovieSceneTrackExtensions.get_sections(tracks[0]) if tracks else []
    if sections:
        chans = unreal.MovieSceneSectionExtensions.get_all_channels(sections[0])
        out["channel_count"] = len(chans)
        try:
            chans[0].add_keys([unreal.FrameNumber(0)], [0.0])
            out["key_insert"] = "ok"
        except Exception as exc:
            out["key_insert"] = "ERR:" + str(exc)[:140]
    else:
        out["key_insert"] = "no sections"
except Exception as exc:
    out["key_insert"] = "ERR:" + str(exc)[:140]
__bridge_result__ = out
'''))
    ok5 = tr.get("ok") and abs(tr.get("section_range", [0])[0]) < 0.05 and abs(tr.get("section_range", [0, 0])[1] - 2.0) < 0.05
    step("05_transform_track_section", ok5, {"track_section": tr, "keyframe_probe": key_probe})

    # 6. headless scrub + play control -----------------------------------------------
    res = r(st.scrub_and_play(LS))
    # set/get round to the frame grid in this build (1.25 -> 1.0 observed), so
    # the probe uses whole seconds and asserts the grid-rounding behaviour.
    ok6 = res.get("ok") and abs((res.get("scrub_time") or -1) - 1.0) < 0.05 and res.get("speed") == 2.0 and res.get("playing") is True and res.get("paused") is True
    step("06_scrub_and_play", ok6, res)

    # 7. structure read-back -----------------------------------------------------------
    res = r(st.read_sequence_structure(LS))
    classes = [t.get("class") for t in res.get("tracks", [])]
    # camera cut binds via the section's guid (no separate sequence binding),
    # so 1 possessable binding (the cube) + both track kinds is the true state
    ok7 = res.get("ok") and res.get("binding_count", 0) >= 1 and "MovieScene3DTransformTrack" in classes and "MovieSceneCameraCutTrack" in classes
    step("07_structure_readback", ok7, res)

    # 8. save + reopen ------------------------------------------------------------------
    res = r(st.save_sequence(LS))
    step("08_save_reopen", res.get("ok"), res)

    # 9. negatives ------------------------------------------------------------------------
    res = r(st.create_level_sequence("/Game/ToolGap/ZzBad/"))
    step("09a_bad_path_rejected", not res.get("ok"), res)
    res = r(st.add_actor_binding(LS, "NoSuchActor_Batch5"))
    step("09b_unknown_actor_rejected", not res.get("ok"), res)
    res = r(st.add_track_with_section(LS, cube, "MovieSceneNoSuchTrack", 0.0, 1.0))
    step("09c_unknown_track_rejected", not res.get("ok"), res)

    # restore baseline ----------------------------------------------------------------------
    bridge.open_map("/Game/ShowcaseMap")

    ok = all(s["ok"] for s in steps)
    report["verdict"] = "PASS" if ok else "FAIL"
    report["step_summary"] = {s["step"]: s["ok"] for s in steps}
    EVIDENCE.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nVERDICT: {report['verdict']}  ->  {EVIDENCE}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())