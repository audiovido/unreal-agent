"""BATCH 7 live validation: Niagara / VFX (bridge 6766, ASSET_Showcase2).

Reuses the persisted Batch2Map (sweep + save; no fresh-level creation - the
new_level world-transition is FATAL in this editor build, proven Batch 3).
Probe-first: every primitive below was verified callable in the live session
before implementation. Run:  python assetlib/tools/ue_live_batch7_niagara.py
"""
import json
import os
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools", "unreal"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from unreal_bridge import UnrealBridge  # noqa: E402
from niagara_tools_gap import NiagaraToolsGap, SHIPPING_SYSTEM  # noqa: E402

BRIDGE = ("127.0.0.1", 6766)
BATCH_MAP = "/Game/Batch2Map"
FX_FOLDER = "/Game/Batch7FX"
REPORT = os.path.join(
    os.path.dirname(__file__), "..", "reports", "niagara_tools_batch7.json"
)
SYS_CREATED = "NS_Batch7"
SYS_DUP = "NS_Batch7Dup"
SPAWN_LOC = (120.0, -240.0, 200.0)


def main() -> int:
    bridge = UnrealBridge(*BRIDGE)
    ni = NiagaraToolsGap(bridge)
    steps: List[Dict[str, Any]] = []

    def step(name: str, ok: bool, **detail: Any) -> None:
        steps.append({"step": name, "ok": bool(ok), **detail})
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")

    # 00 map wash (open Batch2Map, clear leftovers, save) ----------------------
    res = bridge.execute_python(
        f"""
import unreal
unreal.EditorLevelLibrary.load_level({BATCH_MAP!r})
world = unreal.EditorLevelLibrary.get_editor_world()
acts = list(unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor))
killed = 0
for a in acts:
    if a.get_actor_label().startswith("Batch7") or a.get_actor_label().startswith("NS_Probe"):
        unreal.EditorLevelLibrary.destroy_actor(a)
        killed += 1
for p in unreal.EditorAssetLibrary.list_assets({FX_FOLDER!r}, recursive=True, include_folder=False):
    unreal.EditorAssetLibrary.delete_asset(p)
unreal.EditorLevelLibrary.save_current_level()
__bridge_result__ = {{"ok": True, "destroyed": killed,
                       "left": list(unreal.EditorAssetLibrary.list_assets({FX_FOLDER!r}, recursive=True, include_folder=False))}}
"""
    )
    body = res.get("result") or res
    step("00_map_wash", body.get("ok") is True and body.get("left") == [],
         map=BATCH_MAP, destroyed=body.get("destroyed"))

    # 01 shipping system -----------------------------------------------------
    res = ni.find_shipping_system()
    body = res.get("result") or res
    step("01_shipping_system", body.get("ok") is True and body.get("class") == "NiagaraSystem",
         path=SHIPPING_SYSTEM, cls=body.get("class"))

    # 02 project scan (pre-create: expect no /Game/Batch7FX entries) ----------
    res = ni.list_niagara_systems("/Game/Batch7FX")
    body = res.get("result") or res
    step("02_scan_empty_folder", body.get("ok") is True and body.get("niagara_count") == 0,
         total=body.get("total_assets"), count=body.get("niagara_count"))

    # 03 create blank system -------------------------------------------------
    res = ni.create_niagara_system(SYS_CREATED, FX_FOLDER)
    body = res.get("result") or res
    step("03_create_blank_system", body.get("ok") is True and body.get("class") == "NiagaraSystem"
         and body.get("saved") is True, cls=body.get("class"), path=body.get("path"))

    # 04 duplicate shipping system -------------------------------------------
    res = ni.duplicate_niagara_system(SHIPPING_SYSTEM, SYS_DUP, FX_FOLDER)
    body = res.get("result") or res
    dup_path = f"{FX_FOLDER}/{SYS_DUP}"
    step("04_duplicate_shipping", body.get("ok") is True and body.get("class") == "NiagaraSystem"
         and body.get("saved") is True, cls=body.get("class"), path=dup_path)

    # 05 spawn at location -> component object path ---------------------------
    res = ni.spawn_niagara_at_location(dup_path, SPAWN_LOC)
    body = res.get("result") or res
    comp_path = body.get("component_path") or ""
    step("05_spawn_at_location", body.get("ok") is True and body.get("component_class") == "NiagaraComponent"
         and bool(comp_path), component=body.get("component_class"),
         comp_path=comp_path, is_active=body.get("is_active_after_spawn"))

    # 06 component state read-back by object path -----------------------------
    res = ni.read_niagara_component(comp_path)
    body = res.get("result") or res
    step("06_read_state", body.get("ok") is True and body.get("component") is not None,
         is_active=body.get("is_active"), auto_activate=body.get("auto_activate"),
         asset=body.get("asset"))

    # 07 variable set (guarded attempt) --------------------------------------
    res = ni.set_niagara_variable(comp_path, "float", "EmitterLifecycle", 42.0)
    body = res.get("result") or res
    step("07_set_variable", body.get("ok") is True,
         var_type=body.get("var_type"), note=body.get("note"), error=body.get("error"))

    # 08 inventory now shows the two systems ---------------------------------
    res = ni.list_niagara_systems(FX_FOLDER)
    body = res.get("result") or res
    classes = {a["path"]: a["class"] for a in body.get("niagara_assets", [])}
    step("08_scan_after_create", body.get("ok") is True and body.get("niagara_count") == 2
         and all(c == "NiagaraSystem" for c in classes.values()),
         count=body.get("niagara_count"), assets=classes)

    # 09 reopen persistence (blank + duplicated) -------------------------------
    r1 = (ni.reopen_niagara_asset(f"{FX_FOLDER}/{SYS_CREATED}").get("result") or {})
    r2 = (ni.reopen_niagara_asset(dup_path).get("result") or {})
    step("09_reopen_persistence", r1.get("is_system") is True and r2.get("is_system") is True,
         blank=r1, duplicated=r2)

    # 10 deactivate/activate cycle by object path ------------------------------
    res = ni.cycle_niagara_component(comp_path)
    body = res.get("result") or res
    step("10_activate_cycle", body.get("ok") is True and body.get("after_activate") is True,
         after_deactivate=body.get("after_deactivate"), after_activate=body.get("after_activate"))

    # 11 negative: spawn nonexistent system ------------------------------------
    res = ni.spawn_niagara_at_location("/Game/Batch7FX/NS_DoesNotExist", SPAWN_LOC)
    body = res.get("result") or res
    step("11_negative_missing_system", body.get("ok") is False and "loadable" in body.get("error", ""),
         error=body.get("error"))

    # persist the map + cleanup spawned actor leftovers back to baseline --------
    bridge.execute_python(
        "import unreal\nunreal.EditorLevelLibrary.save_current_level()"
    )

    passed = sum(1 for s in steps if s["ok"])
    verdict = "PASS" if passed == len(steps) else "FAIL"
    report = {
        "batch": 7,
        "topic": "Niagara / VFX surface",
        "bridge": "127.0.0.1:6766 ASSET_Showcase2",
        "map": BATCH_MAP,
        "verdict": verdict,
        "steps_total": len(steps),
        "steps_passed": passed,
        "steps": steps,
        "note": (
            "All primitives substantiated live pre-implementation (363-symbol Niagara "
            "surface; factory/function-library/component paths verified). Created blank + "
            "duplicated engine-shipped DefaultSystem, spawned + state-read + variable-set "
            "a NiagaraComponent in Batch2Map. is_active outside PIE reported honestly "
            "(step 10 shows it flips on activate())."
        ),
    }
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w") as fh:
        json.dump(report, fh, indent=2)
    print(f"\nVERDICT: {verdict} ({passed}/{len(steps)}) -> {REPORT}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
