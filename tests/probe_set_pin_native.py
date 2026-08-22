from tools.unreal.unreal_bridge import UnrealBridge
import pprint

b = UnrealBridge()

code = r"""
import unreal

ok = unreal.UnrealAgentBlueprintLibrary.set_pin_default_value_by_title(
    "/Game/AgentTests/BP_GraphBridgeSmoke",
    "EventGraph",
    "PrintString",
    "InString",
    "BRIDGE_PROBE_OK"
)

__bridge_result__ = {"set_default_ok": bool(ok)}
"""

pprint.pp(b.execute_python(code))
