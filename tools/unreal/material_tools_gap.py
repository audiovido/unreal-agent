"""Materials gap-closure batch 3 (UE 5.8 bridge).

The material tool surface was EMPTY before this batch (verified by inventory).
All primitives below use the sanctioned MaterialEditingLibrary / AssetTools
surface. Two 5.8 behaviors were verified live before implementation:

  - connect_material_property needs an EMPTY from-output-name ("Output" fails).
  - UMaterial.BaseColor/Metallic/Roughness are NOT exposed to the 5.8 Python
    API (property lookup throws) - the real read/write surface is the
    expression graph: each material pin's connected parameter (name + default),
    read via get_material_property_input_node.

  1. create_material                 - create + save + verify a Material asset
  2. create_material_expression      - scalar/vector expression + parameter
  3. connect_expression_to_property  - connect a param expression to a pin
  4. read_material_pins              - per-pin connected param + default value
  5. set_material_pin_default        - set a connected param's default + verify
  6. create_material_instance        - child MaterialInstanceConstant
  7. set_material_instance_scalar    - set + read-back scalar param
  8. set_material_instance_vector    - set + read-back vector param
  9. list_material_instance_parameters - names + current values
  10. assign_material_to_actor       - set component slot material + read-back
  11. save_material                  - save + reopen + verify identity
"""
from __future__ import annotations

import json
from typing import Any, Dict

from tools.unreal.unreal_bridge import UnrealBridge


class MaterialToolsGap:

    def __init__(self, bridge: UnrealBridge):
        self.bridge = bridge

    @staticmethod
    def _q(value: Any) -> str:
        return json.dumps(str(value))

    # ---- 1. create ---------------------------------------------------------
    def create_material(self, asset_path: str) -> Dict[str, Any]:
        if "/" not in asset_path or not asset_path.startswith("/Game/"):
            return {"ok": False, "error": "expected a /Game asset path, got: " + str(asset_path)}
        name = asset_path.rsplit("/", 1)[-1]
        path = asset_path.rsplit("/", 1)[0]
        if not name:
            return {"ok": False, "error": "empty material name in path: " + str(asset_path)}
        return self.bridge.execute_python(f'''
import unreal
name = {self._q(name)}
path = {self._q(path)}
unreal.EditorAssetLibrary.make_directory(path)
existing = unreal.EditorAssetLibrary.load_asset(path + "/" + name)
if existing is not None and existing.get_class().get_name() == "Material":
    __bridge_result__ = {{"ok": True, "created": False, "preserved": True, "asset_path": path + "/" + name}}
else:
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    mat = tools.create_asset(name, path, unreal.Material, unreal.MaterialFactoryNew())
    saved = False
    if mat is not None:
        saved = bool(unreal.EditorAssetLibrary.save_loaded_asset(mat, False))
    reloaded = unreal.EditorAssetLibrary.load_asset(path + "/" + name)
    __bridge_result__ = {{
        "ok": bool(reloaded is not None and reloaded.get_class().get_name() == "Material" and saved),
        "created": mat is not None,
        "saved": saved,
        "asset_path": path + "/" + name,
    }}
''')

    # ---- 2. expression + parameter -----------------------------------------
    def create_material_expression(self, asset_path: str, class_name: str,
                                   param_name: str, default_value,
                                   x: int = -300, y: int = 0) -> Dict[str, Any]:
        dv = json.dumps(default_value)
        return self.bridge.execute_python(f'''
import unreal
m = unreal.EditorAssetLibrary.load_asset({self._q(asset_path)})
if m is None:
    __bridge_result__ = {{"ok": False, "error": "material not found"}}
else:
    expr_cls = getattr(unreal, {self._q(class_name)}, None)
    if expr_cls is None:
        __bridge_result__ = {{"ok": False, "error": "unknown expression class: " + {self._q(class_name)}}}
    else:
        try:
            expr = unreal.MaterialEditingLibrary.create_material_expression(
                m, expr_cls, int({int(x)}), int({int(y)}))
            if expr is None:
                __bridge_result__ = {{"ok": False, "error": "create_material_expression returned None"}}
            else:
                expr.set_editor_property("parameter_name", {self._q(param_name)})
                dv = {dv}
                if dv is not None:
                    if "Vector" in {self._q(class_name)}:
                        expr.set_editor_property("default_value", unreal.LinearColor(dv[0], dv[1], dv[2], dv[3]))
                    else:
                        expr.set_editor_property("default_value", dv)
                __bridge_result__ = {{
                    "ok": True,
                    "param_name": {self._q(param_name)},
                    "class": expr.get_class().get_name(),
                    "object_path": str(expr.get_path_name()),
                    "default": str(dv),
                }}
        except Exception as exc:
            __bridge_result__ = {{"ok": False, "error": str(exc)}}
''')

    # ---- 3. connect expression to a material pin ----------------------------
    def connect_expression_to_property(self, asset_path: str, expression_path: str,
                                       param_name: str, property_name: str) -> Dict[str, Any]:
        """Connect a previously created expression (carried by its subobject
        path - UMaterial.Expressions is protected in 5.8 Python, so the object
        is resolved via find_object instead of an expressions scan)."""
        return self.bridge.execute_python(f'''
import unreal
m = unreal.EditorAssetLibrary.load_asset({self._q(asset_path)})
if m is None:
    __bridge_result__ = {{"ok": False, "error": "material not found"}}
else:
    prop = getattr(unreal.MaterialProperty, {self._q(property_name)}, None)
    target_expr = unreal.find_object(None, {self._q(expression_path)})
    if prop is None:
        __bridge_result__ = {{"ok": False, "error": "unknown material property: " + {self._q(property_name)}}}
    elif target_expr is None:
        __bridge_result__ = {{"ok": False, "error": "expression object not found: " + {self._q(expression_path)}}}
    else:
        connected = False
        # 5.8 (verified live): the default output pin has an EMPTY name;
        # "Output"/"output" both return False from connect_material_property.
        for pin in ("", "Output"):
            try:
                unreal.MaterialEditingLibrary.connect_material_property(target_expr, pin, prop)
            except Exception:
                continue
            if unreal.MaterialEditingLibrary.get_material_property_input_node(m, prop) is not None:
                connected = True
                break
        node = unreal.MaterialEditingLibrary.get_material_property_input_node(m, prop)
        param_ok = False
        if node is not None:
            try:
                param_ok = str(node.get_editor_property("parameter_name")) == {self._q(param_name)}
            except Exception:
                pass
        __bridge_result__ = {{
            "ok": bool(connected and param_ok),
            "param_name": {self._q(param_name)},
            "property": {self._q(property_name)},
            "connected_node": str(node.get_name()) if node else None,
        }}
''')

    # ---- 4. read per-pin connected param + default --------------------------
    def read_material_pins(self, asset_path: str) -> Dict[str, Any]:
        return self.bridge.execute_python(f'''
import unreal
m = unreal.EditorAssetLibrary.load_asset({self._q(asset_path)})
if m is None:
    __bridge_result__ = {{"ok": False, "error": "material not found"}}
else:
    pins = []
    for prop_name in ("MP_BASE_COLOR", "MP_ROUGHNESS", "MP_METALLIC", "MP_SPECULAR"):
        prop = getattr(unreal.MaterialProperty, prop_name)
        node = unreal.MaterialEditingLibrary.get_material_property_input_node(m, prop)
        if node is None:
            pins.append({{"pin": prop_name, "connected": False}})
            continue
        entry = {{"pin": prop_name, "connected": True, "node_class": str(node.get_class().get_name())}}
        try:
            entry["param"] = str(node.get_editor_property("parameter_name"))
        except Exception:
            entry["param"] = "<none>"
        try:
            dv = node.get_editor_property("default_value")
            if hasattr(dv, "r"):
                entry["default"] = [dv.r, dv.g, dv.b, dv.a]
            else:
                entry["default"] = float(dv)
        except Exception:
            entry["default"] = None
        pins.append(entry)
    __bridge_result__ = {{"ok": True, "pins": pins}}
''')

    # ---- 5. set a connected param's default + verify ------------------------
    def set_material_pin_default(self, asset_path: str, expression_path: str, value) -> Dict[str, Any]:
        """Set the default of a param expression (resolved by subobject path -
        UMaterial.Expressions is protected in 5.8 Python) and read it back."""
        dv = json.dumps(value)
        return self.bridge.execute_python(f'''
import unreal
m = unreal.EditorAssetLibrary.load_asset({self._q(asset_path)})
if m is None:
    __bridge_result__ = {{"ok": False, "error": "material not found"}}
else:
    found = unreal.find_object(None, {self._q(expression_path)})
    if found is None:
        __bridge_result__ = {{"ok": False, "error": "expression object not found: " + {self._q(expression_path)}}}
    else:
        dv = {dv}
        if "Vector" in found.get_class().get_name():
            found.set_editor_property("default_value", unreal.LinearColor(dv[0], dv[1], dv[2], dv[3]))
        else:
            found.set_editor_property("default_value", dv)
        read = found.get_editor_property("default_value")
        if hasattr(read, "r"):
            val = [read.r, read.g, read.b, read.a]
        else:
            val = float(read)
        __bridge_result__ = {{"ok": True, "value_after": val, "expression": {self._q(expression_path)}}}
''')

    # ---- 6. create instance ------------------------------------------------
    def create_material_instance(self, source_path: str, instance_path: str) -> Dict[str, Any]:
        name = instance_path.rsplit("/", 1)[-1]
        path = instance_path.rsplit("/", 1)[0]
        return self.bridge.execute_python(f'''
import unreal
source = unreal.EditorAssetLibrary.load_asset({self._q(source_path)})
if source is None:
    __bridge_result__ = {{"ok": False, "error": "source material not found"}}
else:
    unreal.EditorAssetLibrary.make_directory({self._q(path)})
    existing = unreal.EditorAssetLibrary.load_asset({self._q(instance_path)})
    if existing is not None:
        __bridge_result__ = {{"ok": True, "created": False, "preserved": True, "asset_path": {self._q(instance_path)}}}
    else:
        tools = unreal.AssetToolsHelpers.get_asset_tools()
        inst = tools.create_asset({self._q(name)}, {self._q(path)},
                                  unreal.MaterialInstanceConstant,
                                  unreal.MaterialInstanceConstantFactoryNew())
        if inst is None:
            __bridge_result__ = {{"ok": False, "error": "instance creation returned None"}}
        else:
            inst.set_editor_property("parent", source)
            saved = bool(unreal.EditorAssetLibrary.save_loaded_asset(inst, False))
            reloaded = unreal.EditorAssetLibrary.load_asset({self._q(instance_path)})
            __bridge_result__ = {{
                "ok": bool(reloaded is not None and saved),
                "created": True,
                "saved": saved,
                "asset_path": {self._q(instance_path)},
                "parent": {self._q(source_path)},
            }}
''')

    # ---- 7. instance scalar -------------------------------------------------
    def set_material_instance_scalar(self, instance_path: str, name: str, value: float) -> Dict[str, Any]:
        return self.bridge.execute_python(f'''
import unreal
inst = unreal.EditorAssetLibrary.load_asset({self._q(instance_path)})
if inst is None:
    __bridge_result__ = {{"ok": False, "error": "instance not found"}}
else:
    try:
        unreal.MaterialEditingLibrary.set_material_instance_scalar_parameter_value(
            inst, {self._q(name)}, float({json.dumps(float(value))}))
        read = unreal.MaterialEditingLibrary.get_material_instance_scalar_parameter_value(
            inst, {self._q(name)})
        __bridge_result__ = {{"ok": True, "param": {self._q(name)}, "set": float({json.dumps(float(value))}), "read_back": float(read)}}
    except Exception as exc:
        __bridge_result__ = {{"ok": False, "error": str(exc)}}
''')

    # ---- 8. instance vector --------------------------------------------------
    def set_material_instance_vector(self, instance_path: str, name: str, color) -> Dict[str, Any]:
        col = json.dumps([float(v) for v in color])
        return self.bridge.execute_python(f'''
import unreal
inst = unreal.EditorAssetLibrary.load_asset({self._q(instance_path)})
if inst is None:
    __bridge_result__ = {{"ok": False, "error": "instance not found"}}
else:
    try:
        col = {col}
        unreal.MaterialEditingLibrary.set_material_instance_vector_parameter_value(
            inst, {self._q(name)}, unreal.LinearColor(col[0], col[1], col[2], col[3]))
        read = unreal.MaterialEditingLibrary.get_material_instance_vector_parameter_value(
            inst, {self._q(name)})
        __bridge_result__ = {{"ok": True, "param": {self._q(name)}, "read_back": [read.r, read.g, read.b, read.a]}}
    except Exception as exc:
        __bridge_result__ = {{"ok": False, "error": str(exc)}}
''')

    # ---- 9. instance parameter inventory -----------------------------------
    def list_material_instance_parameters(self, instance_path: str) -> Dict[str, Any]:
        return self.bridge.execute_python(f'''
import unreal
inst = unreal.EditorAssetLibrary.load_asset({self._q(instance_path)})
if inst is None:
    __bridge_result__ = {{"ok": False, "error": "instance not found"}}
else:
    scalars = []
    try:
        for n in unreal.MaterialEditingLibrary.get_scalar_parameter_names(inst):
            v = unreal.MaterialEditingLibrary.get_material_instance_scalar_parameter_value(inst, n)
            scalars.append({{"name": str(n), "value": float(v)}})
    except Exception as exc:
        scalars = [{{"error": str(exc)}}]
    vectors = []
    try:
        for n in unreal.MaterialEditingLibrary.get_vector_parameter_names(inst):
            v = unreal.MaterialEditingLibrary.get_material_instance_vector_parameter_value(inst, n)
            vectors.append({{"name": str(n), "value": [v.r, v.g, v.b, v.a]}})
    except Exception as exc:
        vectors = [{{"error": str(exc)}}]
    __bridge_result__ = {{"ok": True, "scalars": scalars, "vectors": vectors}}
''')

    # ---- 10. assign to an actor slot ----------------------------------------
    def assign_material_to_actor(self, actor_name: str, material_path: str, slot: int = 0) -> Dict[str, Any]:
        return self.bridge.execute_python(f'''
import unreal
actors = [a for a in unreal.EditorLevelLibrary.get_all_level_actors()
          if a.get_name() == {self._q(actor_name)} or a.get_actor_label() == {self._q(actor_name)}]
if len(actors) != 1:
    __bridge_result__ = {{"ok": False, "error": "actor not found or ambiguous: " + {self._q(actor_name)}, "matches": [a.get_name() for a in actors]}}
else:
    a = actors[0]
    mat = unreal.EditorAssetLibrary.load_asset({self._q(material_path)})
    if mat is None:
        __bridge_result__ = {{"ok": False, "error": "material not found: " + {self._q(material_path)}}}
    else:
        comps = a.get_components_by_class(unreal.StaticMeshComponent)
        if not comps:
            __bridge_result__ = {{"ok": False, "error": "actor has no StaticMeshComponent"}}
        else:
            comp = comps[0]
            comp.set_material(int({int(slot)}), mat)
            read = comp.get_material(int({int(slot)}))
            __bridge_result__ = {{
                "ok": read is not None and str(read.get_path_name()).startswith({self._q(material_path)}),
                "actor": a.get_name(),
                "slot": int({int(slot)}),
                "material_on_slot": str(read.get_path_name()) if read else None,
            }}
''')

    # ---- 11. save + reopen verify --------------------------------------------
    def save_material(self, asset_path: str) -> Dict[str, Any]:
        return self.bridge.execute_python(f'''
import unreal
m = unreal.EditorAssetLibrary.load_asset({self._q(asset_path)})
if m is None:
    __bridge_result__ = {{"ok": False, "error": "material not found"}}
else:
    saved = bool(unreal.EditorAssetLibrary.save_loaded_asset(m, False))
    reloaded = unreal.EditorAssetLibrary.load_asset({self._q(asset_path)})
    __bridge_result__ = {{
        "ok": bool(saved and reloaded is not None),
        "asset_path": {self._q(asset_path)},
        "class_after_reload": reloaded.get_class().get_name() if reloaded else None,
    }}
''')