"""BATCH 8 live validation: Landscape / foliage / PCG (bridge 6766).

Final planned breadth batch. Reuses persisted Batch2Map (sweep + save - no
fresh-level creation, fatal in this editor build). Probe-first: landscape
CREATION is recorded as an engine gap (no LandscapeEditorSubsystem mirror);
foliage-type asset authoring, InstancedFoliageActor instancing, and PCG graph
authoring were all verified callable before implementation.
Run:  python assetlib/tools/ue_live_batch8_terrain.py
"""
import json
import os
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools", "unreal"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from unreal_bridge import UnrealBridge  # noqa: E402
from terrain_tools_gap import TerrainToolsGap  # noqa: E402

BRIDGE = ("127.0.0.1", 6766)
BATCH_MAP = "/Game/Batch2Map"
ENV_FOLDER = "/Game/Batch8Env"
REPORT = os.path.join(
    os.path.dirname(__file__), "..", "reports", "terrain_tools_batch8.json"
)
FT_NAME = "FT_Batch8Grass"
PCG_NAME = "PCG_Batch8Graph"


def main() -> int:
    bridge = UnrealBridge(*BRIDGE)
    tt = TerrainToolsGap(bridge)
    steps: List[Dict[str, Any]] = []

    def step(name: str, ok: bool, **detail: Any) -> None:
        steps.append({"step": name, "ok": bool(ok), **detail})
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")

    # 00 map wash -------------------------------------------------------------
    res = bridge.execute_python(
        f"""
import unreal
unreal.EditorLevelLibrary.load_level({BATCH_MAP!r})
world = unreal.EditorLevelLibrary.get_editor_world()
killed = 0
for a in list(unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor)):
    if a.get_actor_label().startswith("Batch8"):
        unreal.EditorLevelLibrary.destroy_actor(a)
        killed += 1
for p in unreal.EditorAssetLibrary.list_assets({ENV_FOLDER!r}, recursive=True, include_folder=False):
    unreal.EditorAssetLibrary.delete_asset(p)
unreal.EditorLevelLibrary.save_current_level()
__bridge_result__ = {{"ok": True, "destroyed": killed}}
"""
    )
    body = res.get("result") or res
    step("00_map_wash", body.get("ok") is True, map=BATCH_MAP, destroyed=body.get("destroyed"))

    # 01 landscape surface probe + creation gap -------------------------------
    res = tt.landscape_surface_probe()
    body = res.get("result") or res
    step("01_landscape_surface", body.get("ok") is True and body.get("total", 0) >= 60
         and body.get("creation_closed") is True,
         total=body.get("total"), key_classes=body.get("key_classes"),
         gap=body.get("gap"))

    # 02 pre-scan (folder empty) ----------------------------------------------
    res = tt.list_terrain_assets(ENV_FOLDER)
    body = res.get("result") or res
    step("02_scan_empty", body.get("ok") is True and body.get("terrain_count") == 0,
         total=body.get("total_assets"), count=body.get("terrain_count"))

    # 03 create foliage type --------------------------------------------------
    res = tt.create_foliage_type(FT_NAME, ENV_FOLDER, "/Engine/BasicShapes/Cube")
    body = res.get("result") or res
    ft_path = f"{ENV_FOLDER}/{FT_NAME}"
    step("03_create_foliage_type", body.get("ok") is True
         and body.get("class") == "FoliageType_InstancedStaticMesh" and body.get("mesh_set") is True,
         cls=body.get("class"), path=body.get("path"), mesh_set=body.get("mesh_set"))

    # 04 spawn foliage instances ----------------------------------------------
    res = tt.spawn_foliage_instances(ft_path, count=4, origin=(60.0, -60.0, 0.0), spacing=150.0)
    body = res.get("result") or res
    step("04_foliage_instances", body.get("ok") is True and body.get("instances_requested") == 4,
         actor=body.get("actor"), requested=body.get("instances_requested"),
         error=body.get("error"))

    # 05 create PCG graph ------------------------------------------------------
    res = tt.create_pcg_graph(PCG_NAME, ENV_FOLDER)
    body = res.get("result") or res
    pcg_path = f"{ENV_FOLDER}/{PCG_NAME}"
    step("05_create_pcg_graph", body.get("ok") is True and body.get("class") == "PCGGraph",
         cls=body.get("class"), path=body.get("path"))

    # 06 author PCG graph ------------------------------------------------------
    res = tt.author_pcg_graph(pcg_path)
    body = res.get("result") or res
    nodes = body.get("nodes_added") or []
    ok_nodes = [n for n in nodes if n.get("node")]
    step("06_author_pcg_graph", body.get("ok") is True and len(ok_nodes) == 2
         and (body.get("edges") or []) != [], nodes=nodes, edges=body.get("edges"),
         edge_errors=body.get("edge_errors"), total_edges=body.get("total_edges"))

    # 07 scan after create ------------------------------------------------------
    res = tt.list_terrain_assets(ENV_FOLDER)
    body = res.get("result") or res
    classes = {a["path"]: a["class"] for a in body.get("terrain_assets", [])}
    step("07_scan_after_create", body.get("ok") is True and body.get("terrain_count") == 2
         and "FoliageType_InstancedStaticMesh" in classes.values() and "PCGGraph" in classes.values(),
         count=body.get("terrain_count"), assets=classes)

    # 08 reopen persistence ------------------------------------------------------
    r1 = (tt.reopen_terrain_asset(ft_path).get("result") or {})
    r2 = (tt.reopen_terrain_asset(pcg_path).get("result") or {})
    step("08_reopen_persistence", r1.get("class") == "FoliageType_InstancedStaticMesh"
         and r2.get("class") == "PCGGraph", foliage=r1, pcg=r2)

    bridge.execute_python("import unreal\nunreal.EditorLevelLibrary.save_current_level()")

    passed = sum(1 for s in steps if s["ok"])
    verdict = "PASS" if passed == len(steps) else "FAIL"
    report = {
        "batch": 8,
        "topic": "Landscape / foliage / PCG (final breadth batch)",
        "bridge": "127.0.0.1:6766 ASSET_Showcase2",
        "map": BATCH_MAP,
        "verdict": verdict,
        "steps_total": len(steps),
        "steps_passed": passed,
        "steps": steps,
        "note": (
            "Landscape CREATION recorded as an engine gap (no LandscapeEditorSubsystem/"
            "LandscapeSubsystem mirror - 65 landscape symbols present but the editor "
            "tool is C++-only, same class as IK retarget). Foliage type asset + "
            "InstancedFoliageActor instances and PCG graph authoring (2 nodes + edges) "
            "live-validated. PCG runtime generation not substantiable (no PCGSubsystem)."
        ),
    }
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w") as fh:
        json.dump(report, fh, indent=2)
    print(f"\nVERDICT: {verdict} ({passed}/{len(steps)}) -> {REPORT}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
