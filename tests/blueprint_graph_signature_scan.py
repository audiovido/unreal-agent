from tools.unreal.unreal_bridge import UnrealBridge
import pprint

b = UnrealBridge()

code = r'''
targets = {
    "list_graph_names":
        unreal.BlueprintEditorLibrary.list_graph_names.__doc__,

    "find_event_graph":
        getattr(unreal.BlueprintEditorLibrary, "find_event_graph", None).__doc__
        if getattr(unreal.BlueprintEditorLibrary, "find_event_graph", None)
        else None,

    "add_function_graph":
        getattr(unreal.BlueprintEditorLibrary, "add_function_graph", None).__doc__
        if getattr(unreal.BlueprintEditorLibrary, "add_function_graph", None)
        else None,

    "add_event_graph":
        getattr(unreal.BlueprintEditorLibrary, "add_event_graph", None).__doc__
        if getattr(unreal.BlueprintEditorLibrary, "add_event_graph", None)
        else None,

    "add_node_event":
        getattr(unreal.BlueprintEditorLibrary, "add_node_event", None).__doc__
        if getattr(unreal.BlueprintEditorLibrary, "add_node_event", None)
        else None,

    "add_node_call_function":
        getattr(unreal.BlueprintEditorLibrary, "add_node_call_function", None).__doc__
        if getattr(unreal.BlueprintEditorLibrary, "add_node_call_function", None)
        else None,

    "connect_nodes":
        getattr(unreal.BlueprintEditorLibrary, "connect_nodes", None).__doc__
        if getattr(unreal.BlueprintEditorLibrary, "connect_nodes", None)
        else None,
}

__bridge_result__ = {
    "ok": True,
    "docs": targets
}
'''

pprint.pp(b.execute_python(code))
