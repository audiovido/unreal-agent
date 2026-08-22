from tools.unreal.unreal_bridge import UnrealBridge
import pprint

b = UnrealBridge()

code = r"""
import unreal

bp = "/Game/AgentTests/BP_GraphBridgeSmoke"

nodes = unreal.UnrealAgentBlueprintLibrary.list_graph_nodes(
    bp,
    "EventGraph"
)

__bridge_result__ = {
    "nodes": [str(x) for x in nodes]
}
"""

pprint.pp(b.execute_python(code))
