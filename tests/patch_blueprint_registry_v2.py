from pathlib import Path

path = Path("core/tool_registry.py")
text = path.read_text(encoding="utf-8")

# 1) Initialize BlueprintTools when live bridge exists
marker = """    if bridge is not None:
        registry.update({"""

replacement = """    if bridge is not None:
        from tools.unreal.blueprint_tools import BlueprintTools
        blueprints = BlueprintTools(bridge)

        registry.update({"""

if "blueprints = BlueprintTools(bridge)" not in text:
    if marker not in text:
        raise SystemExit("ERROR: bridge registry marker not found.")
    text = text.replace(marker, replacement, 1)


# 2) Insert Blueprint tools immediately before registry.update closes
marker = """            func=bridge.save_level,
            destructive=True,
        ),
    })"""

replacement = """            func=bridge.save_level,
            destructive=True,
        ),

        "create_blueprint": ToolSpec(
            name="create_blueprint",
            description="Create a Blueprint asset with an Unreal parent class.",
            args={
                "asset_path": "Content path such as /Game/Agent/BP_Test",
                "parent_class": "Unreal parent class such as Actor",
            },
            func=blueprints.create_blueprint,
            destructive=True,
        ),

        "inspect_blueprint": ToolSpec(
            name="inspect_blueprint",
            description="Inspect Blueprint variables, graphs, and components.",
            args={
                "asset_path": "Blueprint content path",
            },
            func=blueprints.inspect_blueprint,
        ),

        "add_blueprint_variable": ToolSpec(
            name="add_blueprint_variable",
            description="Add a member variable to a Blueprint.",
            args={
                "asset_path": "Blueprint content path",
                "variable_name": "Variable name",
                "variable_type": "Blueprint basic type such as Float, Int, Bool, String",
            },
            func=blueprints.add_blueprint_variable,
            destructive=True,
        ),

        "add_blueprint_component": ToolSpec(
            name="add_blueprint_component",
            description="Add a component to a Blueprint.",
            args={
                "asset_path": "Blueprint content path",
                "component_class": "Component class such as StaticMeshComponent",
                "component_name": "Component name",
            },
            func=blueprints.add_blueprint_component,
            destructive=True,
        ),

        "compile_blueprint": ToolSpec(
            name="compile_blueprint",
            description="Compile a Blueprint asset.",
            args={
                "asset_path": "Blueprint content path",
            },
            func=blueprints.compile_blueprint,
            destructive=True,
        ),

        "save_blueprint": ToolSpec(
            name="save_blueprint",
            description="Save a Blueprint asset.",
            args={
                "asset_path": "Blueprint content path",
            },
            func=blueprints.save_blueprint,
            destructive=True,
        ),
    })"""

if '"create_blueprint": ToolSpec(' not in text:
    if marker not in text:
        raise SystemExit("ERROR: save_level end marker not found.")
    text = text.replace(marker, replacement, 1)

path.write_text(text, encoding="utf-8")

print("BLUEPRINT REGISTRY PATCH: OK")
