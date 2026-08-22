from tools.unreal.unreal_bridge import UnrealBridge
import pprint

b = UnrealBridge()

code = r"""
import unreal

bp = "/Game/AgentTests/BP_GraphBridgeSmoke"

node = unreal.UnrealAgentBlueprintLibrary.add_call_function_node(
    bp,
    "EventGraph",
    "/Script/Engine.KismetSystemLibrary",
    "PrintString",
    350,
    0
)

__bridge_result__ = {
    "ok": node is not None,
    "repr": str(node) if node else None,
}
"""

pprint.pp(b.execute_python(code))
