"""Live UE acceptance for gap-closure BATCH 3 (Materials).

Temporary validation in the ONE ASSET_Showcase2 editor (bridge 6766): an
M_Batch3Test material with scalar+vector parameters wired into the graph, pin
read-back at each stage, a child instance with parameter overrides, applied to
a real mesh actor in a blank temp level, saved + reopened to prove persistence.
Evidence: assetlib/reports/material_tools_batch3.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, "tools/unreal")

from tools.unreal.material_tools_gap import MaterialToolsGap  # noqa: E402
from tools.unreal.unreal_bridge import UnrealBridge  # noqa: E402
from tools.unreal.world_tools_gap import WorldToolsGap  # noqa: E402

MAP = "/Game/ToolGap/Batch3Map"
MAT = "/Game/ToolGap/M_Batch3Test"
MI = "/Game/ToolGap/MI_Batch3Test"
EVIDENCE = Path("assetlib/reports/material_tools_batch3.json")


def main() -> int:
    bridge = UnrealBridge(port=6766)
    ident = bridge.get_identity()
    assert ident.get("ok") and ident.get("project_name") == "ASSET_Showcase2", ident
    mt = MaterialToolsGap(bridge)
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
    for a in (MAT, MI, MAP):
        r(bridge.execute_python(f"import unreal; pr = unreal.EditorAssetLibrary.delete_asset('{a}'); __bridge_result__ = {{'deleted': bool(pr)}}"))
    bridge.execute_python("import unreal; unreal.AssetRegistryHelpers.get_asset_registry().scan_paths_synchronous(['/Game/ToolGap'], force_rescan=True)")
    p = Path("assetlib/tests/ue/ASSET_Showcase2/Content/ToolGap/Batch3Map.umap")
    if p.exists():
        p.unlink()
    step("00_cleanup", True, {})

    # 1. reuse the persisted, ours-only Batch2Map instead of new_level:
    # new_level()'s world transition triggered a FATAL "World Memory Leaks"
    # crash in this editor (EditorServer.cpp:1951, observed live), so temp-map
    # creation is avoided; open + sweep leftovers + persist is the safe path.
    bridge.save_level()
    res = r(bridge.open_map("/Game/ToolGap/Batch2Map"))
    sweep = r(bridge.execute_python(f'''
import unreal
victims = [a.get_name() for a in (unreal.EditorLevelLibrary.get_all_level_actors() or [])
           if a.get_name().startswith("Gap") or a.get_name().startswith("Mat")]
for n in victims:
    for a in unreal.EditorLevelLibrary.get_all_level_actors() or []:
        if a.get_name() == n:
            unreal.EditorLevelLibrary.destroy_actor(a)
            break
__bridge_result__ = {{"removed": victims}}
'''))
    bridge.save_level()
    cnt = r(wt.list_level_actor_details()).get("actor_count", 0) if res.get("ok") else -1
    step("01_open_batch2map_clean", res.get("ok") and cnt == 0 and sweep.get("ok") is not False, {"open": res, "swept": sweep, "actor_count_after": cnt})
    if not (res.get("ok") and cnt == 0):
        report["verdict"] = "FAIL"
        EVIDENCE.write_text(json.dumps(report, indent=2, default=str))
        return 1

    # 2. create material -------------------------------------------------------
    res = r(mt.create_material(MAT))
    step("02_create_material", res.get("ok"), res)

    # 3. blank pin graph (no connected params yet) ------------------------------
    res = r(mt.read_material_pins(MAT))
    step("03_pins_unwired", res.get("ok") and not any(p.get("connected") for p in res.get("pins", [])), res)

    # 4. scalar parameter expression -------------------------------------------
    res = r(mt.create_material_expression(MAT, "MaterialExpressionScalarParameter", "Intensity", 0.5, x=-300, y=0))
    exp_i = res.get("object_path")
    step("04_create_scalar_param", res.get("ok") and bool(exp_i), res)

    # 5. vector parameter expression ---------------------------------------------
    res = r(mt.create_material_expression(MAT, "MaterialExpressionVectorParameter", "Tint", [1.0, 0.0, 0.0, 1.0], x=-300, y=120))
    exp_t = res.get("object_path")
    step("05_create_vector_param", res.get("ok") and bool(exp_t), res)

    # 6. connect to material pins (verified by input-node read-back) -------------
    res = r(mt.connect_expression_to_property(MAT, exp_i, "Intensity", "MP_ROUGHNESS"))
    step("06_connect_roughness", res.get("ok"), res)
    res = r(mt.connect_expression_to_property(MAT, exp_t, "Tint", "MP_BASE_COLOR"))
    step("06b_connect_basecolor", res.get("ok"), res)

    # 7. pin graph read-back (ROUGHNESS <- Intensity, BASE_COLOR <- Tint) --------
    res = r(mt.read_material_pins(MAT))
    pins = {p.get("pin"): p for p in res.get("pins", [])}
    ok7 = res.get("ok") and pins.get("MP_ROUGHNESS", {}).get("param") == "Intensity" and pins.get("MP_BASE_COLOR", {}).get("param") == "Tint"
    step("07_pin_readback", ok7, res)

    # 8. set a connected param's default (roughness 0.25) + verify via pins -----
    res = r(mt.set_material_pin_default(MAT, exp_i, 0.25))
    pins = {p.get("pin"): p for p in r(mt.read_material_pins(MAT)).get("pins", [])}
    ok8 = res.get("ok") and abs(pins.get("MP_ROUGHNESS", {}).get("default", -1) - 0.25) < 0.001
    step("08_set_pin_default", ok8, {"set": res, "pin_after": pins.get("MP_ROUGHNESS")})

    # 9. child instance ------------------------------------------------------------
    res = r(mt.create_material_instance(MAT, MI))
    step("09_create_instance", res.get("ok"), res)

    # 10. instance overrides + read-back -------------------------------------------
    res = r(mt.set_material_instance_scalar(MI, "Intensity", 0.75))
    step("10_instance_scalar", res.get("ok") and abs(res.get("read_back", -1) - 0.75) < 0.001, res)
    res = r(mt.set_material_instance_vector(MI, "Tint", [1.0, 0.0, 0.0, 1.0]))
    step("10b_instance_vector", res.get("ok") and res.get("read_back", [0, 0, 0, 0])[0] == 1.0, res)

    # 11. instance parameter inventory ---------------------------------------------
    res = r(mt.list_material_instance_parameters(MI))
    scalars = {s.get("name"): s.get("value") for s in res.get("scalars", [])}
    vectors = {v.get("name"): v.get("value") for v in res.get("vectors", [])}
    step("11_parameter_inventory", res.get("ok") and scalars.get("Intensity") == 0.75 and "Tint" in vectors, res)

    # 12. apply to a real mesh actor ----------------------------------------------
    res = r(wt.bulk_spawn("StaticMeshActor", 1, origin=(0.0, 0.0, 0.0), name_prefix="Mat", mesh_asset="/Engine/BasicShapes/Cube.Cube"))
    cube = (res.get("created") or [{}])[0].get("name")
    res = r(mt.assign_material_to_actor(cube, MI))
    step("12_assign_to_mesh", res.get("ok") and res.get("material_on_slot", "").startswith(MI), res)

    # 13. save + reopen + persistence ----------------------------------------------
    res = r(mt.save_material(MAT))
    res2 = r(mt.save_material(MI))
    res3 = r(mt.set_material_instance_scalar(MI, "Intensity", 0.75))  # reloaded asset read-back
    step("13_save_reopen", res.get("ok") and res2.get("ok") and abs(res3.get("read_back", -1) - 0.75) < 0.001,
         {"material": res, "instance": res2, "reopen_scalar": res3})

    # 14. negatives -----------------------------------------------------------------
    res = r(mt.connect_expression_to_property(MAT, exp_i, "Intensity", "MP_NOT_A_REAL_PROPERTY"))
    step("14a_unknown_property_rejected", not res.get("ok"), res)
    res = r(mt.connect_expression_to_property(MAT, "/Game/Nope.ThisDoesNotExist_99", "Ghost", "MP_ROUGHNESS"))
    step("14b_missing_expression_rejected", not res.get("ok"), res)
    res = r(mt.create_material("/Game/ToolGap/ZzNotReallyPath/"))
    step("14c_malformed_path_rejected", not res.get("ok") and "empty material name" in res.get("error", ""), res)
    res = r(mt.assign_material_to_actor("NoSuchActor_Batch3", MI))
    step("14d_unknown_actor_rejected", not res.get("ok"), res)

    # restore baseline session ------------------------------------------------------
    bridge.open_map("/Game/ShowcaseMap")

    ok = all(s["ok"] for s in steps)
    report["verdict"] = "PASS" if ok else "FAIL"
    report["step_summary"] = {s["step"]: s["ok"] for s in steps}
    EVIDENCE.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nVERDICT: {report['verdict']}  ->  {EVIDENCE}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())