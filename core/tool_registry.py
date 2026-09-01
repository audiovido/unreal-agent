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
    create_project,
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

        "create_project": ToolSpec(
            name="create_project",
            description="Create a new Unreal project using the configured engine.",
            args={
                "project_name": "New project name",
                "destination": "Directory where the project will be created",
                "template": "Unreal project template name"
            },
            func=create_project,
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

    # ------------------------------------------------------------- blender
    from tools.blender.blender_tools import BlenderTools

    blender_tools = BlenderTools()

    registry.update({
        "blender_status": ToolSpec(
            name="blender_status",
            description="Verify the Blender executable and version (headless).",
            args={},
            func=blender_tools.blender_status,
        ),

        "blender_create_asset": ToolSpec(
            name="blender_create_asset",
            description="Create a 3D asset procedurally in headless Blender (cube/table/cylinder/sphere/monkey...) and export it to the asset exchange for Unreal import.",
            args={
                "name": "Asset/object name",
                "shape": "Primitive shape: cube, plane, cylinder, sphere, cone, torus, monkey, or table",
                "dimensions_cm": "Optional [x, y, z] target dimensions in centimeters",
                "materials": "Optional material preset name (wood/metal/white...) or list of them",
                "export_format": "Export format: fbx, glb or gltf",
                "export_dir": "Optional output directory",
                "screenshot": "Render a headless proof screenshot (default true)",
                "timeout_seconds": "Blender timeout in seconds (default 600)",
                "max_attempts": "Retry budget (default 3)",
            },
            func=blender_tools.blender_create_asset,
        ),

        "blender_convert_asset": ToolSpec(
            name="blender_convert_asset",
            description="Convert an existing asset file (FBX/GLB/GLTF/OBJ) to another format through headless Blender.",
            args={
                "source": "Absolute path to the source asset file",
                "export_format": "Target format: fbx, glb or gltf",
                "name": "Optional output object name",
                "export_dir": "Optional output directory",
                "cleanup": "Run mesh cleanup before export (default true)",
                "timeout_seconds": "Blender timeout in seconds (default 600)",
                "max_attempts": "Retry budget (default 3)",
            },
            func=blender_tools.blender_convert_asset,
        ),

        "blender_prepare_asset": ToolSpec(
            name="blender_prepare_asset",
            description="Clean up, apply transforms, fix origin, normalize scale, UV-unwrap and export a mesh for Unreal through headless Blender.",
            args={
                "source": "Optional source file; when omitted a primitive is generated",
                "name": "Object name",
                "export_format": "Export format: fbx, glb or gltf",
                "materials": "Optional material preset name or list",
                "target_dimension_cm": "Optional target largest-axis dimension in centimeters",
                "decimate_ratio": "Optional decimation ratio (0..1)",
                "uv_unwrap": "Run smart UV unwrap (default true)",
                "export_dir": "Optional output directory",
                "timeout_seconds": "Blender timeout in seconds (default 600)",
                "max_attempts": "Retry budget (default 3)",
            },
            func=blender_tools.blender_prepare_asset,
        ),

        "blender_prepare_character": ToolSpec(
            name="blender_prepare_character",
            description="Prepare a real character asset (mesh + skeleton + animations) for Unreal through headless Blender. Returns REALISTIC_CHARACTER_SOURCE_REQUIRED when no realistic character source exists.",
            args={
                "source": "Optional source character file (FBX/GLB)",
                "name": "Character object name",
                "export_format": "Export format (default fbx)",
                "target_height_cm": "Optional target height in centimeters",
                "export_dir": "Optional output directory",
                "timeout_seconds": "Blender timeout in seconds (default 600)",
                "max_attempts": "Retry budget (default 3)",
            },
            func=blender_tools.blender_prepare_character,
        ),

        "blender_inspect_asset": ToolSpec(
            name="blender_inspect_asset",
            description="Import a source asset inside headless Blender and report its meshes, armature, materials, textures and animations.",
            args={
                "source": "Absolute path to the source asset file",
                "timeout_seconds": "Blender timeout in seconds (default 600)",
                "max_attempts": "Retry budget (default 3)",
            },
            func=blender_tools.blender_inspect_asset,
        ),

        "blender_job_status": ToolSpec(
            name="blender_job_status",
            description="Return the persisted record of one Blender job (status, validation, manifest).",
            args={"job_id": "Blender job id"},
            func=blender_tools.blender_job_status,
        ),

        "blender_jobs_list": ToolSpec(
            name="blender_jobs_list",
            description="List recent Blender jobs (id, operation, status).",
            args={"limit": "Optional maximum number of jobs (default 20)"},
            func=blender_tools.blender_jobs_list,
        ),

        "blender_cancel_job": ToolSpec(
            name="blender_cancel_job",
            description="Request cancellation of a running Blender job.",
            args={"job_id": "Blender job id"},
            func=blender_tools.blender_cancel_job,
        ),

        "blender_recover": ToolSpec(
            name="blender_recover",
            description="Detect interrupted Blender jobs after a restart and resume/retry them without duplicating completed exports.",
            args={},
            func=blender_tools.blender_recover,
        ),

        "blender_verify_export": ToolSpec(
            name="blender_verify_export",
            description="Re-validate the exported file and metadata manifest of a completed Blender job.",
            args={"job_id": "Blender job id"},
            func=blender_tools.blender_verify_export,
        ),
    })

    if bridge is not None:
        from tools.unreal.blueprint_tools import BlueprintTools
        from tools.unreal.avatar_tools import AvatarTools
        from tools.unreal.chat_tools import ChatTools
        from tools.unreal.runtime_tools import RuntimeTools
        from tools.unreal.import_tools import ImportTools

        blueprints = BlueprintTools(bridge)
        avatar_tools = AvatarTools(bridge)
        chat_tools = ChatTools(bridge)
        runtime_tools = RuntimeTools(bridge)
        import_tools = ImportTools(bridge)


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

            "get_project_identity": ToolSpec(
                name="get_project_identity",
                description="Return the exact Unreal project currently open in the live Editor.",
                args={},
                func=bridge.get_project_identity,
            ),

            "create_default_level": ToolSpec(
                name="create_default_level",
                description="Create and save a real Unreal level in the currently open project.",
                args={"level_path": "Unreal map path such as /Game/Main"},
                func=bridge.create_default_level,
                destructive=True,
            ),

            "open_map": ToolSpec(
                name="open_map",
                description=(
                    "Reopen a real /Game map (or the persisted EditorStartupMap "
                    "when no path is given) and verify the active world identity."
                ),
                args={"level_path": "Optional Unreal map path such as /Game/Maps/Main"},
                func=bridge.open_map,
            ),

            "validate_project_creation": ToolSpec(
                name="validate_project_creation",
                description="Strictly validate active project identity, loaded level, visible mesh actor, and clean saved state.",
                args={
                    "project_name": "Expected active Unreal project name",
                    "actor_name": "Expected visible actor label",
                },
                func=bridge.validate_project_creation,
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
                    "location": "XYZ array such as [0, 0, 100]",
                    "rotation": "Optional Pitch/Yaw/Roll array",
                    "scale": "Optional XYZ scale array",
                    "actor_name": "Optional Outliner label",
                    "mesh_asset": "Optional static mesh asset path"
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

            "delete_asset": ToolSpec(
                name="delete_asset",
                description="Delete an Unreal content asset.",
                args={
                    "asset_path": "Asset content path such as /Game/MyFolder/MyAsset"
                },
                func=bridge.delete_asset,
                destructive=True,
            ),        "save_level": ToolSpec(
            name="save_level",
            description="Save dirty Unreal level and project packages.",
            args={},
            func=bridge.save_level,
            destructive=True,
        ),

        # ---------------------------------------------------- blender import
        "create_asset_folder": ToolSpec(
            name="create_asset_folder",
            description="Create a Content Browser folder for imported assets.",
            args={"folder_path": "Content path such as /Game/Imported"},
            func=import_tools.create_asset_folder,
        ),

        "import_asset": ToolSpec(
            name="import_asset",
            description="Import an FBX/GLB/GLTF file into the Content Browser through the real editor factory and verify the imported asset.",
            args={
                "source_path": "Absolute path to the source asset file",
                "destination_path": "Content folder such as /Game/Imported",
            },
            func=import_tools.import_asset,
        ),

        "import_asset_fbx": ToolSpec(
            name="import_asset_fbx",
            description="Import an FBX file into the Content Browser and verify the imported asset.",
            args={
                "source_path": "Absolute path to the .fbx file",
                "destination_path": "Content folder such as /Game/Imported",
            },
            func=import_tools.import_asset_fbx,
        ),

        "import_asset_gltf": ToolSpec(
            name="import_asset_gltf",
            description="Import a GLB/GLTF file into the Content Browser and verify the imported asset.",
            args={
                "source_path": "Absolute path to the .glb/.gltf file",
                "destination_path": "Content folder such as /Game/Imported",
            },
            func=import_tools.import_asset_gltf,
        ),

        "import_blender_output": ToolSpec(
            name="import_blender_output",
            description="Import the validated export of a completed Blender job (by job id or the latest) into Unreal and persist a handoff record.",
            args={
                "job_id": "Optional Blender job id",
                "destination_path": "Content folder such as /Game/Imported",
            },
            func=import_tools.import_blender_output,
        ),

        "verify_imported_asset": ToolSpec(
            name="verify_imported_asset",
            description="Load an imported asset, prove its class, and read real actor bounds in centimeters.",
            args={"asset_path": "Unreal asset path such as /Game/Imported/Table.Table"},
            func=import_tools.verify_imported_asset,
        ),

        "verify_blender_output": ToolSpec(
            name="verify_blender_output",
            description="Verify the asset imported from a Blender job using the persisted import handoff.",
            args={"job_id": "Optional Blender job id"},
            func=import_tools.verify_blender_output,
        ),

        "inspect_imported_asset": ToolSpec(
            name="inspect_imported_asset",
            description="Inspect an imported asset: class, materials, and real bounds.",
            args={"asset_path": "Unreal asset path"},
            func=import_tools.inspect_imported_asset,
        ),

        "spawn_imported_asset": ToolSpec(
            name="spawn_imported_asset",
            description="Spawn an imported StaticMesh/SkeletalMesh asset into the current level as a verified actor.",
            args={
                "asset_path": "Unreal asset path",
                "actor_name": "Outliner label",
                "location": "Optional XYZ array",
                "rotation": "Optional Pitch/Yaw/Roll array",
                "scale": "Optional XYZ scale array",
            },
            func=import_tools.spawn_imported_asset,
            destructive=True,
        ),

        "spawn_blender_output": ToolSpec(
            name="spawn_blender_output",
            description="Spawn the asset imported from a Blender job (handoff-based) into the current level.",
            args={
                "job_id": "Optional Blender job id",
                "actor_name": "Outliner label (default UA_Blender_Asset)",
                "location": "Optional XYZ array",
                "rotation": "Optional Pitch/Yaw/Roll array",
                "scale": "Optional XYZ scale array",
            },
            func=import_tools.spawn_blender_output,
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

        "set_blueprint_variable_default": ToolSpec(
            name="set_blueprint_variable_default",
            description="Set a Blueprint member variable default value.",
            args={
                "asset_path": "Blueprint content path",
                "variable_name": "Variable name",
                "value": "Default value",
            },
            func=blueprints.set_blueprint_variable_default,
            destructive=True,
        ),

        "get_blueprint_variable_default": ToolSpec(
            name="get_blueprint_variable_default",
            description="Read a Blueprint member variable default value.",
            args={
                "asset_path": "Blueprint content path",
                "variable_name": "Variable name",
            },
            func=blueprints.get_blueprint_variable_default,
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
            description="Compile a Blueprint (or WidgetBlueprint), save it, reload it and verify BS_UP_TO_DATE.",
            args={"asset_path": "Blueprint content path", "strategy": "Optional recovery strategy: rescan or repair"},
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

        "create_umg_widget": ToolSpec(
            name="create_umg_widget",
            description="Create, compile, save and verify a real UMG Widget Blueprint asset.",
            args={"asset_path": "Widget Blueprint content path under /Game/"},
            func=blueprints.create_umg_widget,
            destructive=True,
        ),

        # --------------------------------------------------------------- avatar
        "discover_character_assets": ToolSpec(
            name="discover_character_assets",
            description="Scan the active project for SkeletalMesh / Skeleton / AnimSequence character assets and rank the best candidates.",
            args={
                "mesh_filter": "Optional substring filter applied to asset paths",
                "limit": "Maximum number of character assets to return (default 200)",
            },
            func=avatar_tools.discover_character_assets,
        ),

        "inspect_character_asset": ToolSpec(
            name="inspect_character_asset",
            description="Load one character asset and return its class, skeleton or animation evidence.",
            args={"asset_path": "Unreal asset path such as /Game/Mannequin/Character/Mesh/SK_Mannequin_Female"},
            func=avatar_tools.inspect_character_asset,
        ),

        "install_character_assets": ToolSpec(
            name="install_character_assets",
            description="Install the engine's self-contained generic mannequin package (female/male meshes, skeleton, materials, idle animations) into the active project.",
            args={"target_root": "Optional content root such as /Game/Mannequin (default /Game/Mannequin)"},
            func=avatar_tools.install_character_assets,
            destructive=True,
        ),

        "spawn_character": ToolSpec(
            name="spawn_character",
            description="Spawn the best available character as a verified SkeletalMeshActor (explicit mesh, discovered mesh, or installed female mannequin).",
            args={
                "actor_name": "Outliner label for the character",
                "location": "XYZ array such as [0, 0, 100]",
                "rotation": "Optional Pitch/Yaw/Roll array",
                "scale": "Optional XYZ scale array",
                "mesh_asset": "Optional explicit SkeletalMesh asset path",
            },
            func=avatar_tools.spawn_character,
            destructive=True,
        ),

        "set_character_transform": ToolSpec(
            name="set_character_transform",
            description="Set location/rotation/scale of a character actor and verify read-back.",
            args={
                "actor_name": "Character actor label",
                "location": "Optional XYZ array",
                "rotation": "Optional Pitch/Yaw/Roll array",
                "scale": "Optional XYZ scale array",
            },
            func=avatar_tools.set_character_transform,
            destructive=True,
        ),

        "assign_animation": ToolSpec(
            name="assign_animation",
            description="Assign a real AnimSequence (default: idle) to a character's skeletal mesh component and verify read-back.",
            args={
                "actor_name": "Character actor label",
                "animation_asset": "Optional AnimSequence asset path",
            },
            func=avatar_tools.assign_animation,
            destructive=True,
        ),

        "verify_character_visible": ToolSpec(
            name="verify_character_visible",
            description="Structured read-back of a character actor: class, mesh, animation, location, visibility, bounds.",
            args={"actor_name": "Character actor label"},
            func=avatar_tools.verify_character_visible,
        ),

        "avatar_react": ToolSpec(
            name="avatar_react",
            description="Produce a visible runtime character reaction (bob/look/wave/settle) in the PIE world with transform read-back.",
            args={
                "actor_name": "Character actor label",
                "reaction": "bob, look, wave or settle",
                "amount": "Displacement amount (default 40)",
            },
            func=avatar_tools.avatar_react,
        ),

        # ------------------------------------------------------------- chat / UMG
        "ollama_chat": ToolSpec(
            name="ollama_chat",
            description="Call the real local Ollama HTTP endpoint and return the model response with latency. Never returns a fake response.",
            args={
                "prompt": "User chat prompt",
                "model": "Optional Ollama model name; defaults to the first available local model",
                "system_prompt": "Optional system prompt",
                "timeout": "Request timeout in seconds (default 180)",
            },
            func=chat_tools.ollama_chat,
        ),

        "create_widget_blueprint": ToolSpec(
            name="create_widget_blueprint",
            description="Create, compile, save and verify a real UMG Widget Blueprint asset.",
            args={"asset_path": "Widget Blueprint content path under /Game/"},
            func=chat_tools.create_widget_blueprint,
            destructive=True,
        ),

        "add_text_widget": ToolSpec(
            name="add_text_widget",
            description="Add a real runtime UMG TextBlock to the runtime chat widget tree.",
            args={
                "name": "Unique widget name",
                "text": "Initial text",
                "parent": "Optional parent widget name; defaults to the runtime root",
            },
            func=chat_tools.add_text_widget,
            destructive=True,
        ),

        "add_scroll_box": ToolSpec(
            name="add_scroll_box",
            description="Add a real runtime UMG ScrollBox (conversation history container).",
            args={
                "name": "Unique widget name",
                "parent": "Optional parent widget name",
            },
            func=chat_tools.add_scroll_box,
            destructive=True,
        ),

        "add_editable_text_box": ToolSpec(
            name="add_editable_text_box",
            description="Add a real runtime UMG EditableTextBox (chat text input).",
            args={
                "name": "Unique widget name",
                "hint_text": "Optional placeholder text",
                "parent": "Optional parent widget name",
            },
            func=chat_tools.add_editable_text_box,
            destructive=True,
        ),

        "add_button": ToolSpec(
            name="add_button",
            description="Add a real runtime UMG Button (chat Send control).",
            args={
                "name": "Unique widget name",
                "label": "Optional button label text",
                "parent": "Optional parent widget name",
            },
            func=chat_tools.add_button,
            destructive=True,
        ),

        "bind_button_event": ToolSpec(
            name="bind_button_event",
            description="Bind the real UMG Clicked delegate of a Button to a persistent python handler (Send control wiring).",
            args={
                "widget_name": "Button widget name",
                "handler_name": "Handler key (default on_send_clicked)",
                "attempt_broadcast": "Fire a synthetic click through the real delegate when supported (default true)",
            },
            func=chat_tools.bind_button_event,
            destructive=True,
        ),

        "bind_enter_submit": ToolSpec(
            name="bind_enter_submit",
            description="Bind Enter-to-send through the real UMG OnTextCommitted delegate of an EditableTextBox.",
            args={
                "widget_name": "EditableTextBox widget name",
                "attempt_broadcast": "Fire a synthetic commit through the real delegate when supported (default false)",
            },
            func=chat_tools.bind_enter_submit,
            destructive=True,
        ),

        "add_widget_to_viewport": ToolSpec(
            name="add_widget_to_viewport",
            description="Attach a runtime widget to the real game viewport (requires PIE) via GameViewportSubsystem and verify membership.",
            args={
                "widget_name": "Registered widget name",
                "z_order": "Viewport z-order (default 0)",
            },
            func=chat_tools.add_widget_to_viewport,
        ),

        "set_widget_text": ToolSpec(
            name="set_widget_text",
            description="Set a TextBlock/EditableTextBox runtime text and verify read-back.",
            args={
                "widget_name": "Widget name",
                "text": "New text",
            },
            func=chat_tools.set_widget_text,
            destructive=True,
        ),

        "get_widget_text": ToolSpec(
            name="get_widget_text",
            description="Read the current runtime text of a TextBlock/EditableTextBox.",
            args={"widget_name": "Widget name"},
            func=chat_tools.get_widget_text,
        ),

        "verify_widget_visible": ToolSpec(
            name="verify_widget_visible",
            description="Verify a runtime widget exists, is visible and (during PIE) is attached to the viewport.",
            args={"widget_name": "Widget name"},
            func=chat_tools.verify_widget_visible,
        ),

        "set_ui_state": ToolSpec(
            name="set_ui_state",
            description="Set the assistant UI state (online, thinking, speaking, error) on the status widget.",
            args={
                "state": "online, thinking, speaking or error",
                "widget_name": "Status TextBlock name (default StatusText)",
            },
            func=chat_tools.set_ui_state,
            destructive=True,
        ),

        "verify_ui_state": ToolSpec(
            name="verify_ui_state",
            description="Read and verify the current assistant UI state with history.",
            args={
                "expected_state": "Optional expected state: online, thinking, speaking or error",
                "widget_name": "Status TextBlock name (default StatusText)",
            },
            func=chat_tools.verify_ui_state,
        ),

        "chat_append_bubble": ToolSpec(
            name="chat_append_bubble",
            description="Append a User/Assistant/System bubble to the runtime conversation history.",
            args={
                "kind": "user, assistant or system",
                "text": "Bubble text",
                "history_widget": "History ScrollBox name (default HistoryScroll)",
            },
            func=chat_tools.chat_append_bubble,
            destructive=True,
        ),

        "chat_send_message": ToolSpec(
            name="chat_send_message",
            description="Drive the chat controller: set input text, read it back, dispatch the Send handler, append the user bubble and enter Thinking state.",
            args={
                "message": "Message text",
                "input_widget": "Input EditableTextBox name (default InputBox)",
                "history_widget": "History ScrollBox name (default HistoryScroll)",
                "status_widget": "Status TextBlock name (default StatusText)",
            },
            func=chat_tools.chat_send_message,
            destructive=True,
        ),

        "chat_complete_roundtrip": ToolSpec(
            name="chat_complete_roundtrip",
            description="Full live chat controller call: send -> Thinking -> real local Ollama -> assistant bubble -> Online -> optional avatar reaction.",
            args={
                "message": "User message",
                "model": "Optional Ollama model",
                "system_prompt": "Optional system prompt",
                "history_widget": "History ScrollBox name (default HistoryScroll)",
                "status_widget": "Status TextBlock name (default StatusText)",
                "input_widget": "Input EditableTextBox name (default InputBox)",
                "avatar_name": "Optional character label to react after the response",
                "timeout": "Ollama timeout in seconds (default 180)",
            },
            func=chat_tools.chat_complete_roundtrip,
            destructive=True,
        ),

        # ------------------------------------------------------------- runtime
        "runtime_status": ToolSpec(
            name="runtime_status",
            description="Check whether Play In Editor is running and return the game world identity.",
            args={},
            func=runtime_tools.runtime_status,
        ),

        "runtime_widget_verify": ToolSpec(
            name="runtime_widget_verify",
            description="Verify a runtime chat widget (and optional expected text) while PIE is running.",
            args={
                "widget_name": "Widget name",
                "expected_text": "Optional expected substring in the widget text",
            },
            func=runtime_tools.runtime_widget_verify,
        ),

        "runtime_actor_verify": ToolSpec(
            name="runtime_actor_verify",
            description="Verify a named actor exists (optionally with expected class) in the running PIE world.",
            args={
                "actor_name": "Actor label",
                "actor_class": "Optional expected class such as SkeletalMeshActor",
            },
            func=runtime_tools.runtime_actor_verify,
        ),

        "verify_reopen_state": ToolSpec(
            name="verify_reopen_state",
            description="Read back project identity, active map, persisted startup map and saved state after a reopen.",
            args={
                "expected_project": "Optional expected project name",
                "expected_map": "Optional expected map, such as /Game/Maps/AvaLive_Main",
            },
            func=runtime_tools.verify_reopen_state,
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



