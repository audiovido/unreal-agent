from tools.unreal.unreal_bridge import UnrealBridge
import pprint

b = UnrealBridge()

code = r"""
import unreal

bp = unreal.EditorAssetLibrary.load_asset("/Game/AgentTests/BP_GraphBridgeSmoke")
graphs = bp.get_all_graphs()

result = []

for g in graphs:
    if g.get_name() == "EventGraph":
        for n in g.get_nodes():
            try:
                title = n.get_node_title(unreal.NodeTitleType.LIST_VIEW)
            except:
                title = str(n)

            pins = []
            try:
                for p in n.get_pins():
                    pins.append(str(p.get_name()))
            except:
                pass

            result.append({
                "title": str(title),
                "class": n.get_class().get_name(),
                "pins": pins
            })

__bridge_result__ = result
"""

pprint.pp(b.execute_python(code))
