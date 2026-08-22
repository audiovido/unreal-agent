from __future__ import annotations

from typing import Any, Dict, List

from tools.unreal.unreal_bridge import UnrealBridge


class BlueprintTools:
    def __init__(self, bridge: UnrealBridge):
        self.bridge = bridge

    def create_blueprint(
        self,
        asset_path: str,
        parent_class: str = "Actor",
    ) -> Dict[str, Any]:
        return self.bridge.execute_python(f'''
parent_class = getattr(unreal, "{parent_class}", None)

if parent_class is None:
    __bridge_result__ = {{
        "ok": False,
        "error": "Unknown Unreal parent class: {parent_class}"
    }}
else:
    bp = unreal.BlueprintEditorLibrary.create_blueprint_asset_with_parent(
        "{asset_path}",
        parent_class
    )

    __bridge_result__ = {{
        "ok": bp is not None,
        "asset_path": "{asset_path}",
        "name": bp.get_name() if bp else None,
        "class": bp.get_class().get_name() if bp else None
    }}
''')

    def inspect_blueprint(
        self,
        asset_path: str,
    ) -> Dict[str, Any]:
        return self.bridge.execute_python(f'''
asset = unreal.EditorAssetLibrary.load_asset("{asset_path}")

if asset is None:
    __bridge_result__ = {{
        "ok": False,
        "error": "Blueprint asset not found: {asset_path}"
    }}
else:
    variables = unreal.BlueprintEditorLibrary.list_member_variable_names(asset)
    graphs = unreal.BlueprintEditorLibrary.list_graph_names(asset)

    subobject_subsystem = unreal.get_engine_subsystem(
        unreal.SubobjectDataSubsystem
    )

    handles = subobject_subsystem.k2_gather_subobject_data_for_blueprint(asset)

    components = []

    for handle in handles:
        data = unreal.SubobjectDataBlueprintFunctionLibrary.get_data(handle)

        if data is None:
            continue

        obj = unreal.SubobjectDataBlueprintFunctionLibrary.get_object(data)

        if obj is None:
            continue

        components.append({{
            "name": obj.get_name(),
            "class": obj.get_class().get_name()
        }})

    __bridge_result__ = {{
        "ok": True,
        "asset_path": asset.get_path_name(),
        "name": asset.get_name(),
        "class": asset.get_class().get_name(),
        "variables": [str(v) for v in variables],
        "graphs": [str(g) for g in graphs],
        "components": components
    }}
''')

    def add_blueprint_variable(
        self,
        asset_path: str,
        variable_name: str,
        variable_type: str,
    ) -> Dict[str, Any]:
        return self.bridge.execute_python(f'''
asset = unreal.EditorAssetLibrary.load_asset("{asset_path}")

if asset is None:
    __bridge_result__ = {{
        "ok": False,
        "error": "Blueprint asset not found: {asset_path}"
    }}
else:
    pin_type = unreal.BlueprintEditorLibrary.get_basic_type_by_name(
        "{variable_type}"
    )

    if pin_type is None:
        __bridge_result__ = {{
            "ok": False,
            "error": "Unknown Blueprint variable type: {variable_type}"
        }}
    else:
        result = unreal.BlueprintEditorLibrary.add_member_variable(
            asset,
            "{variable_name}",
            pin_type
        )

        __bridge_result__ = {{
            "ok": bool(result),
            "asset_path": "{asset_path}",
            "variable_name": "{variable_name}",
            "variable_type": "{variable_type}"
        }}
''')

    def add_blueprint_component(
        self,
        asset_path: str,
        component_class: str,
        component_name: str,
    ) -> Dict[str, Any]:
        return self.bridge.execute_python(f"""
asset = unreal.EditorAssetLibrary.load_asset("{asset_path}")

if asset is None:
    __bridge_result__ = {{
        "ok": False,
        "error": "Blueprint asset not found: {asset_path}"
    }}
else:
    component_class = getattr(unreal, "{component_class}", None)

    if component_class is None:
        __bridge_result__ = {{
            "ok": False,
            "error": "Unknown Unreal component class: {component_class}"
        }}
    else:
        subsystem = unreal.get_engine_subsystem(
            unreal.SubobjectDataSubsystem
        )

        handles = subsystem.k2_gather_subobject_data_for_blueprint(asset)

        root_handle = None

        for handle in handles:
            data = unreal.SubobjectDataBlueprintFunctionLibrary.get_data(handle)

            if data is not None and unreal.SubobjectDataBlueprintFunctionLibrary.is_root_component(data):
                root_handle = handle
                break

        if root_handle is None:
            __bridge_result__ = {{
                "ok": False,
                "error": "Blueprint root component handle not found"
            }}
        else:
            params = unreal.AddNewSubobjectParams()
            params.set_editor_property("parent_handle", root_handle)
            params.set_editor_property("new_class", component_class)
            params.set_editor_property("blueprint_context", asset)

            new_handle, fail_reason = subsystem.add_new_subobject(params=params)

            if not unreal.SubobjectDataBlueprintFunctionLibrary.is_handle_valid(new_handle):
                __bridge_result__ = {{
                    "ok": False,
                    "error": "Failed to add Blueprint component",
                    "reason": str(fail_reason)
                }}
            else:
                renamed = subsystem.rename_subobject(
                    new_handle,
                    unreal.Text("{component_name}")
                )

                unreal.BlueprintEditorLibrary.compile_blueprint(asset)
                saved = unreal.EditorAssetLibrary.save_loaded_asset(
                    asset,
                    False
                )

                data = unreal.SubobjectDataBlueprintFunctionLibrary.get_data(
                    new_handle
                )
                obj = unreal.SubobjectDataBlueprintFunctionLibrary.get_object(
                    data
                ) if data is not None else None

                __bridge_result__ = {{
                    "ok": bool(renamed),
                    "asset_path": "{asset_path}",
                    "component_name": "{component_name}",
                    "component_class": "{component_class}",
                    "renamed": bool(renamed),
                    "actual_name": obj.get_name() if obj else None,
                    "actual_class": obj.get_class().get_name() if obj else None,
                    "saved": bool(saved)
                }}
""")

    def compile_blueprint(
        self,
        asset_path: str,
    ) -> Dict[str, Any]:
        return self.bridge.execute_python(f'''
asset = unreal.EditorAssetLibrary.load_asset("{asset_path}")

if asset is None:
    __bridge_result__ = {{
        "ok": False,
        "error": "Blueprint asset not found: {asset_path}"
    }}
else:
    unreal.BlueprintEditorLibrary.compile_blueprint(asset)

    __bridge_result__ = {{
        "ok": True,
        "asset_path": "{asset_path}",
        "compiled": True
    }}
''')

    def save_blueprint(
        self,
        asset_path: str,
    ) -> Dict[str, Any]:
        return self.bridge.execute_python(f'''
asset = unreal.EditorAssetLibrary.load_asset("{asset_path}")

if asset is None:
    __bridge_result__ = {{
        "ok": False,
        "error": "Blueprint asset not found: {asset_path}"
    }}
else:
    saved = unreal.EditorAssetLibrary.save_loaded_asset(
        asset,
        False
    )

    __bridge_result__ = {{
        "ok": bool(saved),
        "asset_path": "{asset_path}",
        "saved": bool(saved)
    }}
''')


