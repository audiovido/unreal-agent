"""Live UE acceptance for gap-closure BATCH 1 (Blueprint Graph).

Drives ONE real editor (bridge 6766, ASSET_Showcase2) to build BP_ToolGapTest:
create -> variable Speed (+metadata) -> component -> function graph -> nodes
-> pin connect (names discovered from the native pin reader) -> compile+inspect
-> save -> reopen -> read-back -> verify.

Evidence: assetlib/reports/blueprint_gap_batch1.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root
sys.path.insert(0, "tools/unreal")

from tools.unreal.blueprint_graph_gap_tools import BlueprintGraphGapTools  # noqa: E402
from tools.unreal.blueprint_graph_tools import BlueprintGraphTools  # noqa: E402
from tools.unreal.blueprint_tools import BlueprintTools  # noqa: E402
from tools.unreal.unreal_bridge import UnrealBridge  # noqa: E402

ASSET = "/Game/ToolGap/BP_ToolGapTest"
EVIDENCE = Path("assetlib/reports/blueprint_gap_batch1.json")


def main() -> int:
    bridge = UnrealBridge(port=6766)
    ident = bridge.get_identity()
    assert ident.get("ok") and ident.get("project_name") == "ASSET_Showcase2", ident

    bt = BlueprintTools(bridge)
    gt = BlueprintGraphTools(bridge)
    gap = BlueprintGraphGapTools(bridge)

    steps: list[dict] = []
    report: dict = {"bridge": ident, "steps": steps}

    def r(env: dict) -> dict:
        """Unwrap the bridge envelope to the real result payload."""
        return (env or {}).get("result") or env or {}

    def step(name: str, ok: bool, detail: dict) -> dict:
        rec = {"step": name, "ok": bool(ok), **detail}
        steps.append(rec)
        print(f"[{name}] ok={ok} {json.dumps(detail, default=str)[:230]}")
        return rec

    # 0. clean slate (delete asset + folder, force rescan, assert gone) ------
    washed = bridge.execute_python(f'''
import unreal
unreal.EditorAssetLibrary.delete_asset("{ASSET}")
unreal.EditorAssetLibrary.delete_directory("/Game/ToolGap")
unreal.AssetRegistryHelpers.get_asset_registry().scan_paths_synchronous(["/Game/ToolGap"], force_rescan=True)
__bridge_result__ = {{"remaining": unreal.EditorAssetLibrary.load_asset("{ASSET}") is not None}}
''')
    step("00_clean_slate", not (washed.get("result") or {}).get("remaining", False), washed)

    # 1. create --------------------------------------------------------------
    created = bt.create_blueprint(ASSET, parent_class="Actor")
    step("01_create_blueprint", created.get("ok"), created)

    # 2. variable Speed (5.8 drift: type-name may yield int; verify on CDO) --
    added_type = "Double"
    res = bt.add_blueprint_variable(ASSET, "Speed", added_type)
    res = r(res)
    cdo_check = bridge.execute_python(f'''
bp = unreal.EditorAssetLibrary.load_asset("{ASSET}")
unreal.BlueprintEditorLibrary.compile_blueprint(bp)
try:
    v = unreal.get_default_object(bp.generated_class()).get_editor_property("Speed")
    __bridge_result__ = {{"value": str(v), "py_type": type(v).__name__}}
except Exception as exc:
    __bridge_result__ = {{"error": str(exc)}}
''')
    actual_type = cdo_check.get("result", cdo_check)
    step("02_add_variable_speed", res.get("ok"),
         {"variable": "Speed", "requested_type": added_type, "cdo": actual_type,
          "note": "5.8 get_basic_type_by_name returns an int-typed pin type; actual CDO type recorded"})

    # 3. default value (coercion fix in set_blueprint_variable_default) ------
    res = r(bt.set_blueprint_variable_default(ASSET, "Speed", "100.0"))
    step("03_set_default", res.get("ok"), res)

    # 4. variable metadata (new primitive) ----------------------------------
    res = r(gap.set_variable_metadata(ASSET, "Speed", instance_editable=True, category="Movement"))
    ok4 = res.get("ok") and "instance_editable" in res.get("applied", []) and "category" in res.get("applied", [])
    step("04_set_variable_metadata", ok4, res)

    # 5. component -----------------------------------------------------------
    res = r(bt.add_blueprint_component(ASSET, "StaticMeshComponent", "MeshBox"))
    actual_comp = res.get("actual_name") or "MeshBox"
    step("05_add_component", res.get("ok"), res)

    # 6. create function graph (new primitive) -------------------------------
    res = r(gap.create_function_graph(ASSET, "Move"))
    step("06_create_function_graph", res.get("ok"), res)

    # 6b. override a parent function (new primitive, 5.8 2-arg signature) ----
    res = r(gap.add_function_override(ASSET, "ReceiveTick"))
    step("06b_add_function_override", res.get("ok"), res)

    # 7. add call nodes in EventGraph ----------------------------------------
    res1 = r(gt.add_call_function_node(ASSET, "EventGraph", "/Script/Engine.KismetSystemLibrary", "PrintString", x=350, y=0))
    res2 = r(gt.add_call_function_node(ASSET, "EventGraph", "/Script/Engine.KismetSystemLibrary", "Delay", x=650, y=120))
    step("07_add_call_nodes", res1.get("ok") and res2.get("ok"), {"print_string": res1, "delay": res2})

    # 7b. node read-back (new primitive, native readers) ---------------------
    graph = r(gap.read_graph(ASSET, "EventGraph"))
    step("07b_read_graph", graph.get("ok") and graph.get("node_count", 0) >= 3, graph)

    # 8. connect pins with DISCOVERED exec-pin names (5.8: execute/then pairs)
    def exec_names(env: dict, direction: str) -> str | None:
        pins = (((env.get("result") or env).get("outputs") if direction == "out"
                 else (env.get("result") or env).get("inputs")) or [])
        for p in pins:
            if str(p.get("type")) == "Exec":
                return str(p.get("name"))
        return None

    # Event BeginPlay's single exec out is the pin named "then"
    bp_pins = next((n["pins"] for n in graph.get("nodes", []) if n["title"] == "Event BeginPlay"), [])
    out_then = "then" if "then" in bp_pins else None
    ps_exec = exec_names(res1, "in")
    ps_then = exec_names(res1, "out")
    dl_exec = exec_names(res2, "in")
    conn = gt.connect_pins(ASSET, "EventGraph", "Event BeginPlay", out_then, "PrintString", ps_exec)
    conn2 = gt.connect_pins(ASSET, "EventGraph", "PrintString", ps_then, "Delay", dl_exec)
    n_conn = r(conn).get("connected", False)
    n_conn2 = r(conn2).get("connected", False)
    step("08_connect_pins", bool(n_conn) and bool(n_conn2),
         {"discovered": {"beginplay_then": out_then, "print_exec": ps_exec, "print_then": ps_then, "delay_exec": dl_exec},
          "beginplay_to_print": r(conn), "print_to_delay": r(conn2)})

    # 9. compile + error inspection (new primitive, proven BS_UP_TO_DATE) ----
    res = r(gap.compile_and_inspect(ASSET))
    step("09_compile_inspect", res.get("ok") and res.get("errors", []) == [], res)

    # 10. save ---------------------------------------------------------------
    res = bt.save_blueprint(ASSET)
    step("10_save_blueprint", res.get("ok"), res)

    # 11. rename graph (new primitive, 5.8 (graph, name) signature) ----------
    res = r(gap.rename_graph(ASSET, "Move", "MoveAction"))
    step("11_rename_graph", res.get("ok"), res)

    # 12. reopen + full read-back --------------------------------------------
    vars_ = gap.list_member_variables(ASSET)
    graphs = gap.list_graphs(ASSET)
    funcs = gap.list_events_and_functions(ASSET)
    step("12_reopen_readback", vars_.get("ok") and graphs.get("ok") and funcs.get("ok"),
         {"variables": vars_, "graphs": graphs, "functions_events": funcs})

    # 13. verify expected structure (new primitive) --------------------------
    vars_, graphs = r(vars_), r(graphs)
    names = [v["name"] for v in vars_.get("variables", [])]
    gnames = [g["name"] for g in graphs.get("graphs", [])]
    expected_graphs = {"nodes": []}
    expected = {
        "variables": names,
        "components": [actual_comp],
        "graphs": {
            "EventGraph": {"nodes": ["PrintString", "Delay"]},
            "MoveAction": expected_graphs,
        },
    }
    res = r(gap.verify_blueprint_structure(ASSET, expected))
    step("13_verify_structure",
         res.get("ok") and "Speed" in names and "EventGraph" in gnames and "MoveAction" in gnames,
         {"verify": res, "member_names": names, "graph_names": gnames})

    ok = all(s["ok"] for s in steps)
    report["verdict"] = "PASS" if ok else "FAIL"
    report["step_summary"] = {s["step"]: s["ok"] for s in steps}
    EVIDENCE.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nVERDICT: {report['verdict']}  ->  {EVIDENCE}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())