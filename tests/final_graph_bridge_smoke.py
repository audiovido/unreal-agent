from __future__ import annotations

import pprint
import time

from tools.unreal.unreal_bridge import UnrealBridge
from tools.unreal.blueprint_tools import BlueprintTools
from tools.unreal.blueprint_graph_tools import BlueprintGraphTools


bridge = UnrealBridge()

connected = False

print("Waiting for Unreal Editor bridge...")

for attempt in range(45):
    try:
        result = bridge.ping()

        if result:
            connected = True
            break
    except Exception:
        pass

    time.sleep(2)


if not connected:
    raise SystemExit(
        "FINAL GRAPH BRIDGE SMOKE: FAIL - Unreal bridge not connected"
    )


print("Unreal bridge connected.")

bp = BlueprintTools(bridge)
graph = BlueprintGraphTools(bridge)

asset = "/Game/AgentTests/BP_GraphBridgeSmoke"


cleanup = bridge.execute_python(r'''
path = "/Game/AgentTests/BP_GraphBridgeSmoke"

exists = unreal.EditorAssetLibrary.does_asset_exist(path)

deleted = True

if exists:
    deleted = unreal.EditorAssetLibrary.delete_asset(path)

__bridge_result__ = {
    "ok": bool(deleted),
    "deleted": bool(deleted)
}
''')

print("\nCLEANUP")
pprint.pp(cleanup)


created = bp.create_blueprint(
    asset,
    "Actor"
)

print("\nCREATE")
pprint.pp(created)


built = graph.build_beginplay_print(
    asset,
    "UNREAL AGENT GRAPH BRIDGE PASS"
)

print("\nGRAPH")
pprint.pp(built)


nodes = graph.list_graph_nodes(
    asset,
    "EventGraph"
)

print("\nNODES")
pprint.pp(nodes)


outer = built.get("result", {}) if isinstance(built, dict) else {}

if not outer.get("ok"):
    raise SystemExit(
        "FINAL GRAPH BRIDGE SMOKE: FAIL"
    )

if not outer.get("connected"):
    raise SystemExit(
        "FINAL GRAPH BRIDGE SMOKE: FAIL - pins not connected"
    )

if int(outer.get("links", 0)) < 1:
    raise SystemExit(
        "FINAL GRAPH BRIDGE SMOKE: FAIL - no graph links"
    )

if not outer.get("saved"):
    raise SystemExit(
        "FINAL GRAPH BRIDGE SMOKE: FAIL - blueprint not saved"
    )

titles = [
    str(x).lower()
    for x in outer.get("nodes", [])
]

if not any(
    "beginplay" in x
    for x in titles
):
    raise SystemExit(
        "FINAL GRAPH BRIDGE SMOKE: FAIL - BeginPlay missing"
    )

if not any(
    "print" in x
    for x in titles
):
    raise SystemExit(
        "FINAL GRAPH BRIDGE SMOKE: FAIL - PrintString missing"
    )


print("")
print("==============================================")
print("FINAL GRAPH BRIDGE SMOKE: PASS")
print("BeginPlay -> PrintString -> Connected")
print("Compiled -> Saved -> Verified")
print("==============================================")
