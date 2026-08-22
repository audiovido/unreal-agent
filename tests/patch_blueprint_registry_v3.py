from pathlib import Path

p = Path("core/tool_registry.py")
lines = p.read_text(encoding="utf-8").splitlines()

# Add BlueprintTools initialization immediately after:
# if bridge is not None:
if not any("blueprints = BlueprintTools(bridge)" in x for x in lines):
    idx = next(
        i for i, x in enumerate(lines)
        if x.strip() == "if bridge is not None:"
    )

    lines[idx + 1:idx + 1] = [
        "        from tools.unreal.blueprint_tools import BlueprintTools",
        "        blueprints = BlueprintTools(bridge)",
        "",
    ]

# Find the closing registry.update({ ... }) belonging to bridge section.
if not any('"create_blueprint": ToolSpec(' in x for x in lines):
    save_idx = next(
        i for i, x in enumerate(lines)
        if '"save_level": ToolSpec(' in x
    )

    close_idx = next(
        i for i in range(save_idx, len(lines))
        if lines[i].strip() == "})"
    )

    block = '''
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
'''.strip("\n").splitlines()

    lines[close_idx:close_idx] = block

p.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("BLUEPRINT REGISTRY PATCH: OK")
