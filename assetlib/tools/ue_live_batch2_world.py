"""Live UE acceptance for gap-closure BATCH 2 (World / actor / level).

Temporary validation level /Game/ToolGap/Batch2Map in the ONE existing
ASSET_Showcase2 editor: bulk spawn -> transforms -> rename -> tags ->
world summary -> save + map reload persistence -> bulk delete.
Evidence: assetlib/reports/world_tools_batch2.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, "tools/unreal")

from tools.unreal.unreal_bridge import UnrealBridge  # noqa: E402
from tools.unreal.world_tools_gap import WorldToolsGap  # noqa: E402

MAP = "/Game/ToolGap/Batch2Map"

EVIDENCE = Path("assetlib/reports/world_tools_batch2.json")


def main() -> int:
    bridge = UnrealBridge(port=6766)
    ident = bridge.get_identity()
    assert ident.get("ok") and ident.get("project_name") == "ASSET_Showcase2", ident
    wt = WorldToolsGap(bridge)

    steps: list[dict] = []
    report: dict = {"bridge": ident, "steps": steps}

    def r(env: dict) -> dict:
        return (env or {}).get("result") or env or {}

    def step(name: str, ok: bool, detail: dict) -> dict:
        # detail may carry its own "ok" (negative tests unpack result payloads);
        # the verdict key must win, so it is spelled LAST.
        rec = {"step": name, **detail, "ok": bool(ok)}
        steps.append(rec)
        print(f"[{name}] ok={ok} {json.dumps(detail, default=str)[:220]}")
        return rec

    # 0. deterministic wash: restore baseline map, drop any leftover Gap*
    # actors (ours), persist, then delete the temp map while it is UNLOADED
    # (an open map is locked and undeletable; new_level also refuses while the
    # current map is dirty, so the baseline is saved first).
    bridge.execute_python('import unreal; unreal.EditorLoadingAndSavingUtils.load_map("/Game/ShowcaseMap"); __bridge_result__ = {"ok": True}')
    wash = r(bridge.execute_python(f'''
import unreal
victims = [a.get_name() for a in (unreal.EditorLevelLibrary.get_all_level_actors() or []) if a.get_name().startswith("Gap")]
for n in victims:
    for a in unreal.EditorLevelLibrary.get_all_level_actors() or []:
        if a.get_name() == n:
            unreal.EditorLevelLibrary.destroy_actor(a)
            break
left = [a.get_name() for a in (unreal.EditorLevelLibrary.get_all_level_actors() or []) if a.get_name().startswith("Gap")]
__bridge_result__ = {{"removed": victims, "remaining": left}}
'''))
    rem, left = wash.get("removed", []), wash.get("remaining", [])
    bridge.save_level()  # persist the clean baseline map (new_level needs it clean)
    dl = r(bridge.execute_python("import unreal; pr = unreal.EditorAssetLibrary.delete_asset('/Game/ToolGap/Batch2Map'); __bridge_result__ = {'deleted': bool(pr)}"))
    bridge.execute_python("import unreal; unreal.AssetRegistryHelpers.get_asset_registry().scan_paths_synchronous(['/Game/ToolGap'], force_rescan=True)")
    # registry delete can leave the backing .umap file; new_level refuses to
    # overwrite an existing file, so remove it from disk as well.
    stale = Path("assetlib/tests/ue/ASSET_Showcase2/Content/ToolGap/Batch2Map.umap")
    if stale.exists():
        stale.unlink()
    step("00_cleanup_prior_map", (wash.get("ok") is not False) and (dl.get("deleted") is not False) and not stale.exists(),
         {"removed": rem, "remaining": left, "temp_map_deleted": dl, "file_removed": not stale.exists()})

    # existing create_default_level makes a BLANK temp validation level.
    res = r(bridge.create_default_level(MAP))
    res2 = r(bridge.open_map(MAP))
    cnt = r(wt.list_level_actor_details()).get("actor_count", 0) if res2.get("ok") else -1
    step("01_create_open_batch2map", res.get("ok") and res2.get("ok") and cnt == 0, {"create": res, "open": res2, "actor_count_after": cnt})
    if not (res.get("ok") and res2.get("ok") and cnt == 0):
        report["verdict"] = "FAIL"
        EVIDENCE.write_text(json.dumps(report, indent=2, default=str))
        return 1

    # 2. bulk spawn 3 static-mesh cubes on a grid (new primitive) -------------
    res = r(wt.bulk_spawn("StaticMeshActor", 3, origin=(0.0, 0.0, 0.0), spacing=(250.0, 250.0, 0.0),
                          name_prefix="Gap", scale=(1.0, 1.0, 1.0), mesh_asset="/Engine/BasicShapes/Cube.Cube"))
    step("02_bulk_spawn", res.get("ok") and len(res.get("created", [])) == 3, res)
    names = [c["name"] for c in res.get("created", [])]

    # 3. set_actor_transform (new primitive, one-shot loc+rot+scale) ----------
    res = r(wt.set_actor_transform(names[0], location=(100.0, 200.0, 50.0), rotation=(0.0, 0.0, 45.0), scale=(2.0, 2.0, 2.0)))
    step("03_set_transform", res.get("ok") and res.get("location") == [100.0, 200.0, 50.0] and res.get("scale") == [2.0, 2.0, 2.0], res)

    # 3b. read-back via the proven get_actor  ---------------------------------
    res = r(bridge.get_actor(names[0]))
    step("03b_transform_readback", res.get("ok") and res.get("location") == [100.0, 200.0, 50.0] and res.get("scale") == [2.0, 2.0, 2.0], res)

    # 4. rename_actor (new primitive) -----------------------------------------
    res = r(wt.rename_actor(names[0], names[0] + "_renamed"))
    renamed = (res.get("name") or names[0])
    step("04_rename_actor", res.get("ok") and renamed.endswith("_renamed"), res)

    # 4b. rename collision guard (boundary) -----------------------------------
    res = r(wt.rename_actor(renamed, names[1]))
    step("04b_rename_collision_guard", not res.get("ok") and ("already used" in res.get("error", "") or "ambiguous" in res.get("error", "")), res)

    # 5. set_actor_tags (new primitive) ----------------------------------------
    res = r(wt.set_actor_tags(renamed, ["batch2", "test"]))
    step("05_set_tags", res.get("ok") and sorted(res.get("tags", [])) == sorted(["batch2", "test"]), res)

    # 6. list_level_actor_details (new primitive) -------------------------------
    res = r(wt.list_level_actor_details())
    rows = res.get("actors", [])
    target = next((x for x in rows if x["name"] == renamed), None)
    step("06_details_query", res.get("ok") and target is not None and sorted(target.get("tags", [])) == sorted(["batch2", "test"]) and target.get("location") == [100.0, 200.0, 50.0], {"actor_count": res.get("actor_count"), "target": target})

    # 7. world_summary (new primitive) ------------------------------------------
    res = r(wt.world_summary())
    step("07_world_summary", res.get("ok") and "Batch2Map" in res.get("map", "") and res.get("actor_count", 0) >= 3
         and res.get("class_histogram", {}).get("StaticMeshActor", 0) == 3, res)

    # 8. persistence: save + reopen the map, verify actors survive (existing) ---
    res = r(bridge.save_level(requested_map=MAP))
    res2 = r(bridge.open_map(MAP))
    res3 = r(wt.list_level_actor_details())
    survivors = [x["name"] for x in res3.get("actors", [])]
    step("08_persistence", bool(res.get("ok")) and bool(res2.get("ok")) and renamed in survivors and names[1] in survivors,
         {"save": res, "open": res2, "survivors": survivors})

    # 9. delete_actors_by_class (new primitive) ---------------------------------
    res = r(wt.delete_actors_by_class("StaticMeshActor"))
    survivors2 = [x["name"] for x in r(wt.list_level_actor_details()).get("actors", [])]
    step("09_delete_by_class", res.get("ok") and res.get("remaining") == 0 and not any(s.startswith("Gap") for s in survivors2), res)

    # 10. boundary: bulk_spawn count 0 refused; unknown actor transform ---------
    res = r(wt.bulk_spawn("StaticMeshActor", 0))
    step("10a_bulk_spawn_zero_validated", not res.get("ok"), res)
    res = r(wt.set_actor_transform("NoSuchActor_Gap", location=(1, 2, 3)))
    step("10b_unknown_actor_validated", not res.get("ok"), res)

    # restore the session to the acceptance baseline map, leave no mess -------
    bridge.open_map("/Game/ShowcaseMap")  # baseline content untouched

    ok = all(s["ok"] for s in steps)
    report["verdict"] = "PASS" if ok else "FAIL"
    report["step_summary"] = {s["step"]: s["ok"] for s in steps}
    EVIDENCE.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nVERDICT: {report['verdict']}  ->  {EVIDENCE}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())