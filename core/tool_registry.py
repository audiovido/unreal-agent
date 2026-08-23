import inspect
from dataclasses import dataclass
from typing import Callable, Dict, Any, List


@dataclass
class ToolSpec:
    name: str
    description: str
    args: Dict[str, str]
    func: Callable
    destructive: bool = False


def build_registry(
    discover_projects,
    inspect_project,
    open_project,
    read_text_file,
    write_text_file,
    run_powershell,
    unreal_status,
    bridge=None,
):
    registry = {
        "discover_projects": ToolSpec(
            name="discover_projects",
            description="Find Unreal .uproject files in common user locations.",
            args={},
            func=discover_projects,
        ),

        "inspect_project": ToolSpec(
            name="inspect_project",
            description="Inspect an Unreal project descriptor and key folders.",
            args={
                "uproject_path": "Absolute path to the .uproject file"
            },
            func=inspect_project,
        ),

        "open_project": ToolSpec(
            name="open_project",
            description="Launch an Unreal project in Unreal Editor.",
            args={
                "uproject_path": "Absolute path to the .uproject file"
            },
            func=open_project,
        ),

        "read_text_file": ToolSpec(
            name="read_text_file",
            description="Read a text file from disk.",
            args={
                "path": "Absolute or resolvable file path"
            },
            func=read_text_file,
        ),

        "write_text_file": ToolSpec(
            name="write_text_file",
            description="Write text content to a file.",
            args={
                "path": "Absolute or resolvable file path",
                "content": "Complete text content to write"
            },
            func=write_text_file,
            destructive=True,
        ),

        "run_powershell": ToolSpec(
            name="run_powershell",
            description="Execute a PowerShell command on the local machine.",
            args={
                "command": "PowerShell command string",
                "timeout": "Timeout in seconds"
            },
            func=run_powershell,
            destructive=True,
        ),

        "unreal_status": ToolSpec(
            name="unreal_status",
            description="Check Unreal Engine installation and editor availability.",
            args={},
            func=unreal_status,
        ),
    }

    if bridge is not None:
        from tools.unreal.blueprint_tools import BlueprintTools
        blueprints = BlueprintTools(bridge)


        registry.update({
            "unreal_ping": ToolSpec(
                name="unreal_ping",
                description="Check whether the live Unreal Editor bridge is connected.",
                args={},
                func=bridge.ping,
            ),

            "list_level_actors": ToolSpec(
                name="list_level_actors",
                description="Return actors currently present in the open Unreal level.",
                args={},
                func=bridge.list_level_actors,
            ),

            "get_selected_actors": ToolSpec(
                name="get_selected_actors",
                description="Return actors currently selected in Unreal Editor.",
                args={},
                func=bridge.get_selected_actors,
            ),

            "is_level_dirty": ToolSpec(
                name="is_level_dirty",
                description="Check whether the currently open Unreal level package has unsaved changes.",
                args={},
                func=bridge.is_level_dirty,
            ),
            "get_current_level": ToolSpec(
                name="get_current_level",
                description="Return information about the currently open Unreal level.",
                args={},
                func=bridge.get_current_level,
            ),

            "start_pie": ToolSpec(
                name="start_pie",
                description="Request Play In Editor for the currently open Unreal level.",
                args={},
                func=bridge.start_pie,
            ),

            "stop_pie": ToolSpec(
                name="stop_pie",
                description="Stop the active Play In Editor session.",
                args={},
                func=bridge.stop_pie,
            ),

            "get_pie_status": ToolSpec(
                name="get_pie_status",
                description="Check whether Play In Editor is currently running and return the game world.",
                args={},
                func=bridge.get_pie_status,
            ),

            "capture_pie_viewport": ToolSpec(
                name="capture_pie_viewport",
                description="Capture the active PIE/game viewport while runtime is playing.",
                args={},
                func=bridge.capture_pie_viewport,
            ),

            "capture_unreal_viewport": ToolSpec(
                name="capture_unreal_viewport",
                description=(
                    "Capture the actual active Unreal Editor viewport "
                    "natively to a PNG file. This is read-only and is "
                    "the preferred visual evidence source."
                ),
                args={},
                func=bridge.capture_unreal_viewport,
            ),

            "visual_review_unreal": ToolSpec(
                name="visual_review_unreal",
                description=(
                    "Capture the actual Unreal Editor viewport natively "
                    "and have the local vision model review composition, "
                    "lighting, scale, materials, environment, and UI/UX. "
                    "Returns structured visual QA feedback."
                ),
                args={},
                func=bridge.visual_review_unreal,
            ),

            "list_assets": ToolSpec(
                name="list_assets",
                description="List Unreal assets under a Content Browser path.",
                args={
                    "path": "Content path such as /Game",
                    "recursive": "True or False"
                },
                func=bridge.list_assets,
            ),

            "get_asset_info": ToolSpec(
                name="get_asset_info",
                description="Load one Unreal asset and return its path, name, and class.",
                args={
                    "asset_path": "Unreal asset path such as /Game/Folder/Asset.Asset"
                },
                func=bridge.get_asset_info,
            ),
            "get_actor": ToolSpec(
                name="get_actor",
                description="Read one Unreal Actor by internal name or Outliner label and return transform data.",
                args={
                    "actor_name": "Actor internal name or Outliner label"
                },
                func=bridge.get_actor,
            ),
            "spawn_actor": ToolSpec(
                name="spawn_actor",
                description="Spawn an Unreal Actor in the currently open level.",
                args={
                    "class_name": "Unreal class name, for example StaticMeshActor",
                    "location": "XYZ array such as [0, 0, 100]"
                },
                func=bridge.spawn_actor,
                destructive=True,
            ),

            "move_actor": ToolSpec(
                name="move_actor",
                description="Move an existing Unreal Actor by name or label.",
                args={
                    "actor_name": "Actor internal name or Outliner label",
                    "location": "XYZ array such as [300, 0, 100]"
                },
                func=bridge.move_actor,
                destructive=True,
            ),

            "rotate_actor": ToolSpec(
                name="rotate_actor",
                description="Rotate an existing Unreal Actor.",
                args={
                    "actor_name": "Actor internal name or Outliner label",
                    "rotation": "Pitch/Yaw/Roll array"
                },
                func=bridge.rotate_actor,
                destructive=True,
            ),

            "scale_actor": ToolSpec(
                name="scale_actor",
                description="Change Actor scale.",
                args={
                    "actor_name": "Actor internal name or Outliner label",
                    "scale": "XYZ scale array such as [2, 2, 2]"
                },
                func=bridge.scale_actor,
                destructive=True,
            ),

            "delete_actor": ToolSpec(
                name="delete_actor",
                description="Delete an Actor from the current level.",
                args={
                    "actor_name": "Actor internal name or Outliner label"
                },
                func=bridge.delete_actor,
                destructive=True,
            ),

            "save_level": ToolSpec(
                name="save_level",
                description="Save dirty Unreal level and project packages.",
                args={},
                func=bridge.save_level,
                destructive=True,
            ),
        "create_blueprint": ToolSpec(
            name="create_blueprint",
            description="Create a Blueprint asset.",
            args={
                "asset_path": "Blueprint content path",
                "parent_class": "Parent Unreal class such as Actor",
            },
            func=blueprints.create_blueprint,
            destructive=True,
        ),

        "inspect_blueprint": ToolSpec(
            name="inspect_blueprint",
            description="Inspect a Blueprint asset.",
            args={"asset_path": "Blueprint content path"},
            func=blueprints.inspect_blueprint,
        ),

        "add_blueprint_variable": ToolSpec(
            name="add_blueprint_variable",
            description="Add a member variable to a Blueprint.",
            args={
                "asset_path": "Blueprint content path",
                "variable_name": "Variable name",
                "variable_type": "Blueprint basic variable type",
            },
            func=blueprints.add_blueprint_variable,
            destructive=True,
        ),

        "add_blueprint_component": ToolSpec(
            name="add_blueprint_component",
            description="Add a component to a Blueprint.",
            args={
                "asset_path": "Blueprint content path",
                "component_class": "Unreal component class",
                "component_name": "Component name",
            },
            func=blueprints.add_blueprint_component,
            destructive=True,
        ),

        "compile_blueprint": ToolSpec(
            name="compile_blueprint",
            description="Compile a Blueprint.",
            args={"asset_path": "Blueprint content path"},
            func=blueprints.compile_blueprint,
            destructive=True,
        ),

        "save_blueprint": ToolSpec(
            name="save_blueprint",
            description="Save a Blueprint.",
            args={"asset_path": "Blueprint content path"},
            func=blueprints.save_blueprint,
            destructive=True,
        ),
        })


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

            "graph_delete_node": ToolSpec(
                name="graph_delete_node",
                description=(
                    "Delete one Blueprint graph node by title. "
                    "Use for explicit graph cleanup and duplicate recovery."
                ),
                args={
                    "asset_path": "Blueprint content path",
                    "graph_name": "Graph name such as EventGraph",
                    "node_title": "Exact or uniquely identifying node title",
                },
                func=graph_tools.delete_node,
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

    return registry


def tool_prompt(registry):
    lines: List[str] = []

    for name, spec in registry.items():
        arg_text = ", ".join(
            f"{key}: {value}"
            for key, value in spec.args.items()
        ) or "none"

        lines.append(
            f"- {name}({arg_text}) | "
            f"destructive={spec.destructive} | "
            f"{spec.description}"
        )

    return "\n".join(lines)


def validate_args(spec: ToolSpec, args: Dict[str, Any]):
    signature = inspect.signature(spec.func)
    declared = set(spec.args)
    required = {
        name
        for name in declared
        if name not in signature.parameters
        or signature.parameters[name].default is inspect.Parameter.empty
    }
    provided = set(args.keys())

    missing = required - provided
    if missing:
        return False, f"Missing required args: {sorted(missing)}"

    unknown = provided - declared
    if unknown:
        return False, f"Unknown args: {sorted(unknown)}"

    return True, ""



