from tools.unreal.unreal_bridge import UnrealBridge
import pprint

b = UnrealBridge()

code = r"""
import unreal

ok = unreal.UnrealAgentBlueprintLibrary.connect_pins_by_title(
    "/Game/AgentTests/BP_GraphBridgeSmoke",
    "EventGraph",
    "Event BeginPlay",
    "then",
    "PrintString",
    "execute"
)

__bridge_result__ = {"connect_ok": bool(ok)}
"""

pprint.pp(b.execute_python(code))
