from pathlib import Path

p = Path("tools/unreal/blueprint_tools.py")
text = p.read_text(encoding="utf-8")

start = text.index("    def add_blueprint_component(")
end = text.index("    def compile_blueprint(", start)

new_func = r'''    def add_blueprint_component(
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

        parent_handle = None

        for handle in handles:
            data = unreal.SubobjectDataBlueprintFunctionLibrary.get_data(handle)

            if data is None:
                continue

            if unreal.SubobjectDataBlueprintFunctionLibrary.is_root_component(data):
                parent_handle = handle
                break

        if parent_handle is None:
            __bridge_result__ = {{
                "ok": False,
                "error": "Blueprint root component handle not found"
            }}
        else:
            params = unreal.AddNewSubobjectParams()
            params.blueprint_context = asset
            params.new_class = component_class
            params.parent_handle = parent_handle

            new_handle, fail_reason = subsystem.add_new_subobject(params)

            if not new_handle.is_valid():
                __bridge_result__ = {{
                    "ok": False,
                    "error": str(fail_reason)
                }}
            else:
                subsystem.rename_subobject(
                    new_handle,
                    unreal.Text("{component_name}")
                )

                unreal.BlueprintEditorLibrary.compile_blueprint(asset)
                unreal.EditorAssetLibrary.save_loaded_asset(asset, False)

                data = unreal.SubobjectDataBlueprintFunctionLibrary.get_data(
                    new_handle
                )

                obj = unreal.SubobjectDataBlueprintFunctionLibrary.get_object(
                    data
                )

                __bridge_result__ = {{
                    "ok": True,
                    "asset_path": "{asset_path}",
                    "component_name": obj.get_name() if obj else "{component_name}",
                    "component_class": (
                        obj.get_class().get_name()
                        if obj else "{component_class}"
                    )
                }}
""")

'''

text = text[:start] + new_func + text[end:]
p.write_text(text, encoding="utf-8")

print("ADD BLUEPRINT COMPONENT PATCH: OK")
