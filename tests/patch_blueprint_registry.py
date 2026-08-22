from pathlib import Path

path = Path("core/tool_registry.py")
text = path.read_text(encoding="utf-8")

needle = '''        "save_level": ToolSpec(
            name="save_level",
            description="Save dirty Unreal level and project packages.",
            args={},
            func=bridge.save_level,
            destructive=True,
        ),
'''

replacement = needle + '''
        "create_blueprint": ToolSpec(
            name="create_blueprint",
            description="Create a Blueprint asset with an Unreal parent class.",
            args={
                "asset_path": "Content path such as /Game/Agent/BP_Test",
                "parent_class": "Unreal parent class such as Actor"
            },
            func=blueprints.create_blueprint,
            destructive=True,
        ),

        "inspect_blueprint": ToolSpec(
            name="inspect_blueprint",
            description="Inspect a Blueprint asset, including variables, graphs, and components.",
            args={
                "asset_path": "Blueprint content path such as /Game/Agent/BP_Test"
            },
            func=blueprints.inspect_blueprint,
        ),

        "add_blueprint_variable": ToolSpec(
            name="add_blueprint_variable",
            description="Add a member variable to a Blueprint.",
            args={
                "asset_path": "Blueprint content path",
                "variable_name": "New variable name",
                "variable_type": "Blueprint basic type name such as Float, Int, Bool, String"
            },
            func=blueprints.add_blueprint_variable,
            destructive=True,
        ),

        "add_blueprint_component": ToolSpec(
            name="add_blueprint_component",
            description="Add a component to a Blueprint.",
            args={
                "asset_path": "Blueprint content path",
                "component_class": "Unreal component class such as StaticMeshComponent",
                "component_name": "New component name"
            },
            func=blueprints.add_blueprint_component,
            destructive=True,
        ),

        "compile_blueprint": ToolSpec(
            name="compile_blueprint",
            description="Compile a Blueprint asset.",
            args={
                "asset_path": "Blueprint content path"
            },
            func=blueprints.compile_blueprint,
            destructive=True,
        ),

        "save_blueprint": ToolSpec(
            name="save_blueprint",
            description="Save a Blueprint asset.",
            args={
                "asset_path": "Blueprint content path"
            },
            func=blueprints.save_blueprint,
            destructive=True,
        ),
'''

if "create_blueprint" in text:
    print("Blueprint registry entries already exist.")
else:
    if needle not in text:
        raise SystemExit("ERROR: save_level block not found; registry was not modified.")

    text = text.replace(needle, replacement, 1)

old = '''if bridge is not None:

        registry.update({'''

new = '''if bridge is not None:
        from tools.unreal.blueprint_tools import BlueprintTools
        blueprints = BlueprintTools(bridge)

        registry.update({'''

if "blueprints = BlueprintTools(bridge)" not in text:
    if old not in text:
        raise SystemExit("ERROR: bridge registry block not found.")
    text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
print("Blueprint registry patch: OK")
