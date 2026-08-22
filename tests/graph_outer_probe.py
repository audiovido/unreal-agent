from tools.unreal.unreal_bridge import UnrealBridge
import pprint

b = UnrealBridge()

code = r'''
asset = unreal.EditorAssetLibrary.load_asset(
    "/Game/AgentTests/BP_AgentSmoke"
)

if asset is None:
    __bridge_result__ = {
        "ok": False,
        "error": "BP_AgentSmoke not found"
    }
else:
    graph = unreal.BlueprintEditorLibrary.find_event_graph(asset)

    result = {
        "graph_found": graph is not None,
        "graph": str(graph),
        "graph_outer": str(graph.get_outer()) if graph else None,
        "tests": {}
    }

    if graph:
        # Probe likely EdGraph properties.
        for prop in [
            "nodes",
            "schema",
            "sub_graphs",
            "graph_guid"
        ]:
            try:
                value = graph.get_editor_property(prop)

                if prop == "nodes":
                    result["tests"][prop] = {
                        "ok": True,
                        "count": len(value),
                        "values": [str(x) for x in value]
                    }
                else:
                    result["tests"][prop] = {
                        "ok": True,
                        "value": str(value)
                    }

            except Exception as exc:
                result["tests"][prop] = {
                    "ok": False,
                    "error": repr(exc)
                }

        # Create a TEMP node with EventGraph as its outer.
        try:
            temp = unreal.new_object(
                unreal.K2Node_CustomEvent,
                outer=graph,
                name="AgentGraphProbe"
            )

            result["temp_node"] = {
                "created": True,
                "object": str(temp),
                "outer": str(temp.get_outer()),
                "title": temp.get_node_title()
            }

            try:
                nodes_after = graph.get_editor_property("nodes")
                result["temp_node"]["present_in_nodes"] = any(
                    x == temp for x in nodes_after
                )
                result["temp_node"]["node_count_after"] = len(nodes_after)
            except Exception as exc:
                result["temp_node"]["nodes_error"] = repr(exc)

        except Exception as exc:
            result["temp_node"] = {
                "created": False,
                "error": repr(exc)
            }

    __bridge_result__ = result
'''

pprint.pp(b.execute_python(code), width=170)
