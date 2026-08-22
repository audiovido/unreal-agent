from pathlib import Path

p = Path("tools/unreal/blueprint_tools.py")
text = p.read_text(encoding="utf-8")

start = text.index("    def add_blueprint_component(")
end = text.index("    def compile_blueprint(", start)

new_method = r'''    def add_blueprint_component(
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

            if not new_handle.is_valid():
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

'''

text = text[:start] + new_method + text[end:]
p.write_text(text, encoding="utf-8")

print("PATCH COMPONENT RENAME: OK")
