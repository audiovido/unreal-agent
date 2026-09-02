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
        """Create a real Blueprint asset (or reuse an existing valid one).

        Never claims success when the path is already occupied by a different
        asset kind (e.g. a World/Level): the structured failure reports the
        exact UE asset class and leaves the asset untouched.
        """
        package_path = asset_path.rsplit("/", 1)[0] if "/" in asset_path else "/Game"
        if str(asset_path).endswith("_C"):
            # A generated class path is never a creatable Blueprint asset.
            return {
                "ok": False,
                "code": "WRONG_ASSET_TYPE",
                "asset_path": asset_path,
                "asset_type": "BlueprintGeneratedClass",
                "name": None,
                "created": False,
                "preserved": False,
                "errors": ["Refusing to create over a generated class path: " + str(asset_path) + " - pass the Blueprint asset path without the _C suffix"],
            }
        return self.bridge.execute_python(f'''
import time
asset_path = {asset_path!r}
package_path = {package_path!r}
parent_class = getattr(unreal, "{parent_class}", None)

if parent_class is None:
    __bridge_result__ = {{
        "ok": False,
        "code": "UNKNOWN_PARENT_CLASS",
        "asset_path": asset_path,
        "asset_type": None,
        "created": False,
        "preserved": False,
        "errors": ["Unknown Unreal parent class: {parent_class}"]
    }}
else:
    unreal.EditorAssetLibrary.make_directory(package_path)
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    registry.scan_paths_synchronous([package_path], force_rescan=True)
    existing = unreal.EditorAssetLibrary.load_asset(asset_path)
    if existing is not None:
        asset_type = existing.get_class().get_name()
        if asset_type not in ("Blueprint", "WidgetBlueprint"):
            # Path occupied by a DIFFERENT asset kind (e.g. a World / Level).
            # Never claim creation success over it and never delete it.
            __bridge_result__ = {{
                "ok": False,
                "code": "WRONG_ASSET_TYPE",
                "asset_path": asset_path,
                "asset_type": asset_type,
                "name": existing.get_name(),
                "created": False,
                "preserved": True,
                "errors": [f"Asset at {{asset_path}} is {{asset_type}}, not a Blueprint; it was left untouched"]
            }}
        else:
            __bridge_result__ = {{
                "ok": True,
                "asset_path": asset_path,
                "asset_type": asset_type,
                "name": existing.get_name(),
                "class": asset_type,
                "created": False,
                "preserved": True,
            }}
    else:
        bp = unreal.BlueprintEditorLibrary.create_blueprint_asset_with_parent(
            asset_path,
            parent_class
        )
        created = bp is not None
        compiled = False
        saved = False
        if bp is not None:
            try:
                unreal.BlueprintEditorLibrary.compile_blueprint(bp)
                compiled = "BS_UP_TO_DATE" in str(bp.status)
            except Exception as exc:
                compiled = False
            saved = bool(unreal.EditorAssetLibrary.save_loaded_asset(bp, False))
        reloaded = unreal.EditorAssetLibrary.load_asset(asset_path)
        asset_type = reloaded.get_class().get_name() if reloaded is not None else (bp.get_class().get_name() if bp is not None else None)
        good = bool(reloaded is not None and asset_type in ("Blueprint", "WidgetBlueprint"))
        __bridge_result__ = {{
            "ok": bool(good),
            "code": None if good else "BLUEPRINT_CREATE_FAILED",
            "asset_path": asset_path,
            "asset_type": asset_type,
            "name": reloaded.get_name() if reloaded is not None else (bp.get_name() if bp is not None else None),
            "class": asset_type,
            "created": created,
            "compiled": compiled,
            "saved": saved,
            "verified": bool(good and saved),
            "errors": [],
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
        _value = "{value}"
        _prop = obj.get_editor_property("{variable_name}")
        # Coerce the string by the property's REAL native type: passing a str
        # to set_editor_property fails on 5.8 numeric properties.
        if isinstance(_value, str):
            if isinstance(_prop, bool):
                _value = _value.strip().lower() in ("true", "1", "yes")
            elif isinstance(_prop, int):
                _value = int(float(_value))
            elif isinstance(_prop, float):
                _value = float(_value)
        obj.set_editor_property("{variable_name}", _value)
        unreal.EditorAssetLibrary.save_loaded_asset(asset, False)
        __bridge_result__ = {{"ok": True, "asset_path": asset.get_path_name(), "variable_name": "{variable_name}", "value": str(_value)}}
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
                    "ok": bool(obj is not None),
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
        strategy: str | None = None,
    ) -> Dict[str, Any]:
        """Compile, save, reload and independently verify a Blueprint asset.

        Supports the Blueprint asset types Unreal Agent itself can create
        ("Blueprint" and "WidgetBlueprint") through the supported UE 5.8 API
        (BlueprintEditorLibrary.compile_blueprint). It never confuses:
          - the asset path string
          - the Blueprint UObject
          - the generated BlueprintGeneratedClass (path ending in _C)
          - the CDO / an instance
          - a WidgetBlueprint
          - a Level/Map (World)

        `strategy` is an optional recovery lever: None (standard compile),
        "rescan" (forced registry rescan + fresh object before compiling),
        "repair" (persist package first, then rescan + fresh object + compile).
        Recovery therefore never repeats the identical failed compile call.
        """
        if not isinstance(asset_path, str) or not asset_path.startswith("/Game/"):
            return {
                "ok": False,
                "code": "INVALID_BLUEPRINT_PATH",
                "asset_path": asset_path,
                "asset_type": None,
                "compile_api": "BlueprintEditorLibrary.compile_blueprint",
                "asset_found": False,
                "is_blueprint": False,
                "compile_called": False,
                "compile_status": None,
                "save_ok": False,
                "verified": False,
                "errors": ["Expected a Blueprint object path under /Game/, not a non-string value"],
                "recoverable": False,
            }
        if str(asset_path).endswith("_C"):
            # Generated-class confusion: the _C object is the compiled output of
            # the Blueprint, not a loadable Blueprint asset. Reject with exact
            # diagnostic so no bridge round-trip is wasted.
            return {
                "ok": False,
                "code": "WRONG_ASSET_TYPE",
                "asset_path": asset_path,
                "asset_type": "BlueprintGeneratedClass",
                "compile_api": "BlueprintEditorLibrary.compile_blueprint",
                "asset_found": False,
                "is_blueprint": False,
                "compile_called": False,
                "compile_status": None,
                "save_ok": False,
                "verified": False,
                "errors": ["Refusing to compile the generated class path: " + str(asset_path) + " - pass the Blueprint asset path without the _C suffix"],
                "recoverable": False,
            }
        lower = asset_path.lower()
        if lower.endswith(".umap") or "/maps/" in lower or "/levels/" in lower:
            # A Level/Map location is never a compilable Blueprint. Reject
            # BEFORE loading so the map package is never touched, and name the
            # exact asset kind so tool evidence says what actually happened.
            return {
                "ok": False,
                "code": "INVALID_BLUEPRINT_PATH",
                "asset_path": asset_path,
                "asset_type": "World (Level/Map path)",
                "compile_api": "BlueprintEditorLibrary.compile_blueprint",
                "asset_found": False,
                "is_blueprint": False,
                "compile_called": False,
                "compile_status": None,
                "save_ok": False,
                "verified": False,
                "errors": ["Refusing to compile a Level/Map as a Blueprint: " + asset_path + " resolves under a map/level folder"],
                "recoverable": False,
            }
        return self.bridge.execute_python(f'''\
import unreal
asset_path = {asset_path!r}
strategy = {strategy!r}
errors = []
asset = unreal.EditorAssetLibrary.load_asset(asset_path)
asset_found = asset is not None
asset_type = asset.get_class().get_name() if asset_found else None
# Blueprints and WidgetBlueprints both derive from Blueprint and compile/save
# through the same editor library; accept both so UMG assets behave like any
# other Blueprint.
is_blueprint = bool(asset_found and asset_type in ("Blueprint", "WidgetBlueprint"))
compile_called = False
save_ok = False
compile_status = None
verified = False
attempts = []
if not asset_found:
    __bridge_result__ = {{
        "ok": False, "code": "BLUEPRINT_NOT_FOUND", "asset_path": asset_path,
        "asset_type": None, "compile_api": "BlueprintEditorLibrary.compile_blueprint",
        "asset_found": False, "is_blueprint": False, "compile_called": False,
        "compile_status": None, "save_ok": False, "verified": False,
        "errors": ["Blueprint asset not found: " + asset_path], "recoverable": True
    }}
elif not is_blueprint:
    hint = ""
    if asset_type == "BlueprintGeneratedClass":
        hint = " (this is the generated class \u2014 pass the Blueprint asset path, without the _C suffix)"
    elif asset_type == "World":
        hint = " (this is a Level/Map \u2014 a Level is never a compilable Blueprint)"
    elif asset_type == "Object":
        hint = " (this looks like a CDO/instance \u2014 pass the Blueprint asset path, not an object instance)"
    __bridge_result__ = {{
        "ok": False, "code": "WRONG_ASSET_TYPE", "asset_path": asset_path,
        "asset_type": asset_type, "compile_api": "BlueprintEditorLibrary.compile_blueprint",
        "asset_found": True, "is_blueprint": False, "compile_called": False,
        "compile_status": None, "save_ok": False, "verified": False,
        "errors": ["Asset is " + asset_type + ", not Blueprint" + hint], "recoverable": False
    }}
else:
    # Up to three changed strategies: original UObject, a fresh reload, then
    # a forced-rescan reload (strategy=rescan) / persisted-package reload
    # (strategy=repair). Never repeat the identical failed compile call.
    candidates = []
    try:
        fresh = unreal.EditorAssetLibrary.load_asset(asset_path)
        if fresh is not asset:
            candidates.append(fresh)
    except Exception as exc:
        errors.append(type(exc).__name__ + ": " + str(exc))
    if strategy in ("rescan", "repair"):
        package_path = asset.get_outer().get_path_name() if asset.get_outer() is not None else asset_path
        try:
            unreal.AssetRegistryHelpers.get_asset_registry().scan_paths_synchronous([package_path], force_rescan=True)
        except Exception as exc:
            errors.append(type(exc).__name__ + ": " + str(exc))
        try:
            fresh = unreal.EditorAssetLibrary.load_asset(asset_path)
            if fresh is not None and fresh is not asset:
                candidates.insert(0, fresh)
        except Exception as exc:
            errors.append(type(exc).__name__ + ": " + str(exc))
        if strategy == "repair":
            try:
                unreal.EditorAssetLibrary.save_loaded_asset(asset, False)
            except Exception as exc:
                errors.append(type(exc).__name__ + ": " + str(exc))
    candidates = [candidate for candidate in candidates if candidate is not None]
    if asset not in candidates:
        candidates.insert(0, asset)
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
            if reloaded is not None:
                asset_type = reloaded.get_class().get_name()
            if verified:
                break
        except Exception as exc:
            errors.append(type(exc).__name__ + ": " + str(exc))
    if not verified and not errors:
        errors.append("Blueprint did not verify as BS_UP_TO_DATE after reload")
    __bridge_result__ = {{
        "ok": bool(verified), "code": None if verified else "BLUEPRINT_COMPILE_FAILED",
        "asset_path": asset_path, "asset_type": asset_type,
        "compile_api": "BlueprintEditorLibrary.compile_blueprint",
        "asset_found": asset_found, "is_blueprint": is_blueprint,
        "compile_called": compile_called, "compile_status": compile_status,
        "save_ok": save_ok, "verified": verified, "errors": errors,
        "recoverable": not verified, "attempts": attempts,
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


