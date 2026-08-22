from tools.unreal.unreal_bridge import UnrealBridge
import pprint

b = UnrealBridge()

code = r"""
import unreal

pins = unreal.UnrealAgentBlueprintLibrary.list_node_pins(
    "/Game/AgentTests/BP_GraphBridgeSmoke",
    "EventGraph",
    "PrintString"
)

__bridge_result__ = {
    "pins": [str(x) for x in pins]
}
"""

pprint.pp(b.execute_python(code))
