from pathlib import Path

path = Path("core/tool_registry.py")

text = path.read_text(encoding="utf-8")

marker = "    return registry\n"

if marker not in text:
    raise SystemExit(
        "ERROR: return registry marker not found"
    )

if '"graph_add_call_function": ToolSpec(' in text:
    print("GRAPH REGISTRY: already installed")
    raise SystemExit(0)

block = r'''
    if bridge is not None:
        from tools.unreal.blueprint_graph_tools import BlueprintGraphTools

        graph_tools = BlueprintGraphTools(bridge)

        registry.update({
            "graph_add_event_override": ToolSpec(
                name="graph_add_event_override",
                description="Add or retrieve an inherited Blueprint event node such as BeginPlay.",
                args={
                    "asset_path": "Blueprint content path",
                    "event_name": "Inherited event name such as ReceiveBeginPlay",
                    "x": "Graph X position",
                    "y": "Graph Y position",
                },
                func=graph_tools.add_event_override,
                destructive=True,
            ),

            "graph_add_call_function": ToolSpec(
                name="graph_add_call_function",
                description="Create a Blueprint CallFunction node using the native Unreal Agent bridge.",
                args={
                    "asset_path": "Blueprint content path",
                    "graph_name": "Graph name such as EventGraph",
                    "function_class_path": "Native class path such as /Script/Engine.KismetSystemLibrary",
                    "function_name": "Native function name such as PrintString",
                    "x": "Graph X position",
                    "y": "Graph Y position",
                },
                func=graph_tools.add_call_function_node,
                destructive=True,
            ),

            "graph_connect_pins": ToolSpec(
                name="graph_connect_pins",
                description="Connect two Blueprint node pins.",
                args={
                    "asset_path": "Blueprint content path",
                    "graph_name": "Graph name",
                    "from_node_title": "Source node title",
                    "from_pin": "Source pin name",
                    "to_node_title": "Destination node title",
                    "to_pin": "Destination pin name",
                },
                func=graph_tools.connect_pins,
                destructive=True,
            ),

            "graph_set_pin_default": ToolSpec(
                name="graph_set_pin_default",
                description="Set a Blueprint graph input pin default value.",
                args={
                    "asset_path": "Blueprint content path",
                    "graph_name": "Graph name",
                    "node_title": "Node title",
                    "pin_name": "Input pin name",
                    "value": "New default value",
                },
                func=graph_tools.set_pin_default,
                destructive=True,
            ),

            "graph_compile_save": ToolSpec(
                name="graph_compile_save",
                description="Compile and save a Blueprint asset.",
                args={
                    "asset_path": "Blueprint content path",
                },
                func=graph_tools.compile_save,
                destructive=True,
            ),

            "graph_list_nodes": ToolSpec(
                name="graph_list_nodes",
                description="List node titles in a Blueprint graph.",
                args={
                    "asset_path": "Blueprint content path",
                    "graph_name": "Graph name",
                },
                func=graph_tools.list_graph_nodes,
            ),

            "graph_build_beginplay_print": ToolSpec(
                name="graph_build_beginplay_print",
                description="Build and verify a BeginPlay to PrintString Blueprint graph.",
                args={
                    "asset_path": "Blueprint content path",
                    "message": "String printed on BeginPlay",
                },
                func=graph_tools.build_beginplay_print,
                destructive=True,
            ),
        })

'''

text = text.replace(
    marker,
    block + marker,
    1
)

path.write_text(
    text,
    encoding="utf-8"
)

print("GRAPH REGISTRY PATCH: OK")
