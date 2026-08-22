from tools.unreal.unreal_bridge import UnrealBridge
import pprint

b = UnrealBridge()

code = r"""
import unreal

bp = "/Game/AgentTests/BP_GraphBridgeSmoke"

ok = unreal.UnrealAgentBlueprintLibrary.set_pin_default_value_by_title(
    bp,
    "EventGraph",
    "PrintString",
    "In String",
    "BRIDGE_PROBE"
)

__bridge_result__ = {"ok": ok}
"""

pprint.pp(b.execute_python(code))
