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
        package_path = asset_path.rsplit("/", 1)[0] if "/" in asset_path else "/Game"
        return self.bridge.execute_python(f'''
import time
parent_class = getattr(unreal, "{parent_class}", None)

if parent_class is None:
    __bridge_result__ = {{
        "ok": False,
        "error": "Unknown Unreal parent class: {parent_class}"
    }}
else:
    unreal.EditorAssetLibrary.make_directory("{package_path}")
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    registry.scan_paths_synchronous(["{package_path}"], force_rescan=True)
    bp = unreal.EditorAssetLibrary.load_asset("{asset_path}")
    if bp is None:
        bp = unreal.BlueprintEditorLibrary.create_blueprint_asset_with_parent(
            "{asset_path}",
            parent_class
        )
    if bp is None:
        time.sleep(0.25)
        registry.scan_paths_synchronous(["{package_path}"], force_rescan=True)
        bp = unreal.EditorAssetLibrary.load_asset("{asset_path}")
    if bp is None:
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

    def set_blueprint_variable_default(
        self,
        asset_path: str,
        variable_name: str,
        value: str,
    ) -> Dict[str, Any]:
        return self.bridge.execute_python(f'''
asset = unreal.EditorAssetLibrary.load_asset("{asset_path}")
if asset is None:
    __bridge_result__ = {{"ok": False, "error": "Blueprint asset not found: {asset_path}"}}
else:
    try:
        unreal.BlueprintEditorLibrary.compile_blueprint(asset)
        obj = unreal.get_default_object(asset.generated_class())
        obj.set_editor_property("{variable_name}", "{value}")
        unreal.EditorAssetLibrary.save_loaded_asset(asset, False)
        __bridge_result__ = {{"ok": True, "asset_path": asset.get_path_name(), "variable_name": "{variable_name}", "value": "{value}"}}
    except Exception as exc:
        __bridge_result__ = {{"ok": False, "error": str(exc)}}
''')

    def get_blueprint_variable_default(
        self,
        asset_path: str,
        variable_name: str,
    ) -> Dict[str, Any]:
        return self.bridge.execute_python(f'''
asset = unreal.EditorAssetLibrary.load_asset("{asset_path}")
if asset is None:
    __bridge_result__ = {{"ok": False, "error": "Blueprint asset not found: {asset_path}"}}
else:
    obj = unreal.get_default_object(asset.generated_class())
    try:
        __bridge_result__ = {{"ok": True, "asset_path": asset.get_path_name(), "variable_name": "{variable_name}", "value": str(obj.get_editor_property("{variable_name}"))}}
    except Exception as exc:
        __bridge_result__ = {{"ok": False, "error": str(exc)}}
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
        """Compile, save, reload and independently verify a Blueprint asset."""
        if not isinstance(asset_path, str) or not asset_path.startswith("/Game/") or ".umap" in asset_path.lower() or "/maps/" in asset_path.lower():
            return {
                "ok": False,
                "code": "INVALID_BLUEPRINT_PATH",
                "asset_path": asset_path,
                "asset_found": False,
                "is_blueprint": False,
                "compile_called": False,
                "save_ok": False,
                "verified": False,
                "errors": ["Expected a Blueprint object path under /Game/, not a Level/Map or non-string value"],
                "recoverable": False,
            }
        return self.bridge.execute_python(f'''\
import unreal
asset_path = {asset_path!r}
errors = []
asset = unreal.EditorAssetLibrary.load_asset(asset_path)
asset_found = asset is not None
# WidgetBlueprints derive from Blueprint and compile/save through the same
# editor library; accept both so UMG assets behave like any other Blueprint.
is_blueprint = bool(asset_found and asset.get_class().get_name() in ("Blueprint", "WidgetBlueprint"))
compile_called = False
save_ok = False
compile_status = None
verified = False
if not asset_found:
    __bridge_result__ = {{
        "ok": False, "code": "BLUEPRINT_NOT_FOUND", "asset_path": asset_path,
        "asset_found": False, "is_blueprint": False, "compile_called": False,
        "compile_status": None, "save_ok": False, "verified": False,
        "errors": ["Blueprint asset not found: " + asset_path], "recoverable": True
    }}
elif not is_blueprint:
    __bridge_result__ = {{
        "ok": False, "code": "WRONG_ASSET_TYPE", "asset_path": asset_path,
        "asset_found": True, "is_blueprint": False, "compile_called": False,
        "compile_status": None, "save_ok": False, "verified": False,
        "errors": ["Asset is " + asset.get_class().get_name() + ", not Blueprint"], "recoverable": False
    }}
else:
    # Up to three changed strategies: original UObject, a fresh reload, then
    # BlueprintEditorLibrary's Blueprint resolver. Never repeat the same object.
    attempts = []
    candidates = [asset]
    try:
        fresh = unreal.EditorAssetLibrary.load_asset(asset_path)
        if fresh is not asset:
            candidates.append(fresh)
    except Exception as exc:
        errors.append(type(exc).__name__ + ": " + str(exc))
    for candidate in candidates[:3]:
        if candidate is None:
            continue
        try:
            if candidate.get_class().get_name() not in ("Blueprint", "WidgetBlueprint"):
                continue
            unreal.BlueprintEditorLibrary.compile_blueprint(candidate)
            compile_called = True
            compile_status = str(candidate.status)
            attempts.append({{"object": candidate.get_name(), "status": compile_status}})
            if "BS_UP_TO_DATE" not in compile_status:
                errors.append(compile_status)
                continue
            save_ok = bool(unreal.EditorAssetLibrary.save_loaded_asset(candidate, False))
            reloaded = unreal.EditorAssetLibrary.load_asset(asset_path)
            reloaded_status = str(reloaded.status) if reloaded is not None else ""
            verified = bool(
                reloaded is not None
                and reloaded.get_class().get_name() in ("Blueprint", "WidgetBlueprint")
                and "BS_UP_TO_DATE" in reloaded_status
                and save_ok
            )
            compile_status = reloaded_status or compile_status
            if verified:
                break
        except Exception as exc:
            errors.append(type(exc).__name__ + ": " + str(exc))
    if not verified and not errors:
        errors.append("Blueprint did not verify as BS_UP_TO_DATE after reload")
    __bridge_result__ = {{
        "ok": bool(verified), "code": None if verified else "BLUEPRINT_COMPILE_FAILED",
        "asset_path": asset_path, "asset_found": asset_found, "is_blueprint": is_blueprint,
        "compile_called": compile_called, "compile_status": compile_status,
        "save_ok": save_ok, "verified": verified, "errors": errors,
        "recoverable": not verified
    }}
''')

    def create_umg_widget(
        self,
        asset_path: str,
    ) -> Dict[str, Any]:
        """Create a real UMG Widget Blueprint asset, compile and save it, and
        independently verify the persisted WidgetBlueprint on disk."""
        if not isinstance(asset_path, str) or not asset_path.startswith("/Game/"):
            return {
                "ok": False,
                "code": "INVALID_WIDGET_PATH",
                "asset_path": asset_path,
                "errors": ["Expected a widget asset path under /Game/"],
            }
        package_path, _, name = asset_path.rpartition("/")
        if not package_path or not name:
            return {"ok": False, "code": "INVALID_WIDGET_PATH", "asset_path": asset_path, "errors": ["Widget path must include a package folder and asset name"]}
        return self.bridge.execute_python(f'''\
import unreal
asset_path = {asset_path!r}
package_path = {package_path!r}
name = {name!r}
errors = []
unreal.EditorAssetLibrary.make_directory(package_path)
asset = unreal.EditorAssetLibrary.load_asset(asset_path)
created = False
if asset is None:
    try:
        factory = unreal.WidgetBlueprintFactory()
        asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
        asset = asset_tools.create_asset(name, package_path, unreal.WidgetBlueprint, factory)
        created = asset is not None
    except Exception as exc:
        errors.append(type(exc).__name__ + ": " + str(exc))
if asset is None:
    __bridge_result__ = {{
        "ok": False, "code": "WIDGET_CREATE_FAILED", "asset_path": asset_path,
        "created": False, "is_widget": False, "compiled": False, "saved": False, "verified": False,
        "errors": errors or ["Unreal could not create the widget asset"],
    }}
else:
    is_widget = asset.get_class().get_name() in ("WidgetBlueprint", "Blueprint")
    compiled = False
    saved = False
    verified = False
    if is_widget:
        try:
            unreal.BlueprintEditorLibrary.compile_blueprint(asset)
            compiled = "BS_UP_TO_DATE" in str(asset.status)
            saved = bool(unreal.EditorAssetLibrary.save_loaded_asset(asset, False))
            reloaded = unreal.EditorAssetLibrary.load_asset(asset_path)
            verified = bool(
                reloaded is not None
                and reloaded.get_class().get_name() in ("WidgetBlueprint", "Blueprint")
                and "BS_UP_TO_DATE" in str(reloaded.status)
                and saved
            )
        except Exception as exc:
            errors.append(type(exc).__name__ + ": " + str(exc))
    __bridge_result__ = {{
        "ok": bool(verified), "code": None if verified else "WIDGET_COMPILE_FAILED",
        "asset_path": asset_path, "created": created, "is_widget": is_widget,
        "compiled": compiled, "saved": saved, "verified": verified,
        "class": asset.get_class().get_name(), "errors": errors,
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


