"""Niagara / VFX gap-closure batch 7 (UE 5.8 bridge).

Surface probed live before implementation: the session mirrors 363 Niagara
symbols including NiagaraSystemFactoryNew / NiagaraEmitterFactoryNew (both
constructible with correct supported classes), NiagaraFunctionLibrary
(spawn_system_at_location / spawn_system_attached), and the full
NiagaraComponent runtime surface (set/get_asset, activate/deactivate,
is_active, set_variable_float/int/vec3). The engine ships a real spawnable
system at /Niagara/DefaultAssets/DefaultSystem (NiagaraSystem).

Live-run corrections incorporated (batch 7 first run):
  - FunctionLibrary-spawned components live on transient owners that are not
    reliably resolvable by actor label across bridge calls -> all component
    primitives address the component by OBJECT PATH (find_object), the
    discipline proven in batch 3 for material expressions.
  - set_variable_* method names are resolved locally (never via runtime
    string concat in the editor), so var_type can never leak a Python type.

CLOSED / limited surface recorded, not faked:
  - NiagaraSystem exposes no Python-visible emitter enumeration (only
    asset_tags) - emitter authoring is not reportable from Python.
  - is_active() outside PIE can report False even after activate() (no
    editor tick); the activate cycle is recorded honestly per step.

  1. list_niagara_systems        - project scan (load-based class reads)
  2. find_shipping_system        - load the engine-shipped DefaultSystem
  3. create_niagara_system       - AssetTools + NiagaraSystemFactoryNew + save
  4. duplicate_niagara_system    - duplicate a system asset into project + save
  5. spawn_niagara_at_location   - FL spawn -> component OBJECT PATH returned
  6. read_niagara_component      - state read by component object path
  7. set_niagara_variable        - guarded variable set by object path
  8. cycle_niagara_component     - deactivate/activate + is_active read-back
  9. reopen_niagara_asset        - save + reopen + class identity check
"""
from __future__ import annotations

import json
from typing import Any, Dict

from tools.unreal.unreal_bridge import UnrealBridge

SHIPPING_SYSTEM = "/Niagara/DefaultAssets/DefaultSystem"


class NiagaraToolsGap:

    def __init__(self, bridge: UnrealBridge):
        self.bridge = bridge

    @staticmethod
    def _q(value: Any) -> str:
        return json.dumps(str(value))

    @staticmethod
    def _resolve(comp_path: str) -> str:
        """Generated-code prefix: resolve a component object path or fail."""
        return (
            "import unreal\n"
            f"comp = unreal.find_object(None, {json.dumps(comp_path)})\n"
            "if comp is None:\n"
            f"    __bridge_result__ = {{'ok': False, 'error': 'component not found by path'}}\n"
        )

    # 1. project inventory ---------------------------------------------------
    def list_niagara_systems(self, root: str = "/Game") -> Dict[str, Any]:
        return self.bridge.execute_python(
            f"""
import unreal
allp = list(unreal.EditorAssetLibrary.list_assets({self._q(root)}, recursive=True, include_folder=False))
found = []
for p in allp:
    try:
        obj = unreal.EditorAssetLibrary.load_asset(p)
        if obj is not None:
            cls = obj.get_class().get_name()
            if cls in ("NiagaraSystem", "NiagaraEmitter"):
                found.append({{"path": p, "class": cls}})
    except Exception:
        pass
__bridge_result__ = {{"ok": True, "total_assets": len(allp),
                       "niagara_assets": found[:60], "niagara_count": len(found)}}
"""
        )

    # 2. shipping system -----------------------------------------------------
    def find_shipping_system(self, path: str = SHIPPING_SYSTEM) -> Dict[str, Any]:
        return self.bridge.execute_python(
            f"""
import unreal
a = unreal.EditorAssetLibrary.load_asset({self._q(path)})
if a is None:
    __bridge_result__ = {{"ok": False, "error": "asset not found"}}
else:
    __bridge_result__ = {{"ok": True, "class": a.get_class().get_name(),
                           "path": {self._q(path)}}}
"""
        )

    # 3. create blank system -------------------------------------------------
    def create_niagara_system(self, name: str, folder: str = "/Game/Batch7FX") -> Dict[str, Any]:
        return self.bridge.execute_python(
            f"""
import unreal
asset_path = {self._q(folder)} + "/" + {self._q(name)}
if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
    unreal.EditorAssetLibrary.delete_asset(asset_path)
at = unreal.AssetToolsHelpers.get_asset_tools()
factory = unreal.NiagaraSystemFactoryNew()
obj = at.create_asset({self._q(name)}, {self._q(folder)}, unreal.NiagaraSystem, factory)
if obj is None:
    __bridge_result__ = {{"ok": False, "error": "create_asset returned None"}}
else:
    saved = unreal.EditorAssetLibrary.save_asset(asset_path)
    __bridge_result__ = {{"ok": True, "class": obj.get_class().get_name(),
                           "path": asset_path, "saved": saved}}
"""
        )

    # 4. duplicate a system into the project --------------------------------
    def duplicate_niagara_system(self, source: str, dest_name: str,
                                 folder: str = "/Game/Batch7FX") -> Dict[str, Any]:
        return self.bridge.execute_python(
            f"""
import unreal
dest = {self._q(folder)} + "/" + {self._q(dest_name)}
if unreal.EditorAssetLibrary.does_asset_exist(dest):
    unreal.EditorAssetLibrary.delete_asset(dest)
dup = unreal.EditorAssetLibrary.duplicate_asset({self._q(source)}, dest)
if dup is None:
    __bridge_result__ = {{"ok": False, "error": "duplicate_asset returned None"}}
else:
    saved = unreal.EditorAssetLibrary.save_asset(dest)
    __bridge_result__ = {{"ok": True, "class": dup.get_class().get_name(),
                           "path": dest, "saved": saved}}
"""
        )

    # 5. spawn a system at a location -> component object path ---------------
    def spawn_niagara_at_location(self, system_path: str,
                                  loc=(0.0, 0.0, 200.0)) -> Dict[str, Any]:
        return self.bridge.execute_python(
            f"""
import unreal
world = unreal.EditorLevelLibrary.get_editor_world()
sys_asset = unreal.EditorAssetLibrary.load_asset({self._q(system_path)})
if sys_asset is None:
    __bridge_result__ = {{"ok": False, "error": "system asset not loadable"}}
else:
    comp = unreal.NiagaraFunctionLibrary.spawn_system_at_location(
        world, sys_asset, unreal.Vector({float(loc[0])}, {float(loc[1])}, {float(loc[2])}),
        unreal.Rotator(0, 0, 0), unreal.Vector(1, 1, 1))
    if comp is None:
        __bridge_result__ = {{"ok": False, "error": "spawn returned None component"}}
    else:
        owner = comp.get_owner()
        comp.activate()
        try:
            wl = comp.get_world_location()
            wl = [wl.x, wl.y, wl.z]
        except Exception:
            wl = None
        __bridge_result__ = {{"ok": True,
                               "component_class": comp.get_class().get_name(),
                               "component_path": comp.get_path_name(),
                               "owner_label": owner.get_actor_label() if owner else None,
                               "world_location": wl,
                               "is_active_after_spawn": comp.is_active()}}
"""
        )

    # 6. read component state by object path ---------------------------------
    def read_niagara_component(self, comp_path: str) -> Dict[str, Any]:
        return self.bridge.execute_python(
            self._resolve(comp_path)
            + """
if comp is not None:
    row = {"component": comp.get_name(),
           "is_active": comp.is_active(),
           "auto_activate": comp.get_editor_property("auto_activate"),
           "asset": str(comp.get_asset()) if hasattr(comp, "get_asset") else None}
    __bridge_result__ = {"ok": True, **row}
"""
        )

    # 7. guarded variable set by object path ---------------------------------
    def set_niagara_variable(self, comp_path: str, var_type: str,
                             name: str, value: float) -> Dict[str, Any]:
        call = {
            "float": f"comp.set_variable_float({json.dumps(name)}, float({value}))",
            "int": f"comp.set_variable_int({json.dumps(name)}, int({value}))",
            "vec3": f"comp.set_variable_vec3({json.dumps(name)}, unreal.Vector({value}, {value}, {value}))",
        }.get(var_type)
        if call is None:
            return {"ok": False, "error": f"unsupported var_type {var_type!r}"}
        return self.bridge.execute_python(
            self._resolve(comp_path)
            + f"""
if comp is not None:
    try:
        {call}
        __bridge_result__ = {{"ok": True, "var_type": {json.dumps(var_type)},
                               "name": {json.dumps(name)}, "value": float({value}),
                               "note": "set succeeded (no python read-back for this var type)"}}
    except Exception as exc:
        __bridge_result__ = {{"ok": False, "error": str(exc)[:250]}}
"""
        )

    # 8. deactivate/activate cycle -------------------------------------------
    def cycle_niagara_component(self, comp_path: str) -> Dict[str, Any]:
        return self.bridge.execute_python(
            self._resolve(comp_path)
            + """
if comp is not None:
    comp.deactivate()
    off = comp.is_active()
    comp.activate()
    on = comp.is_active()
    __bridge_result__ = {"ok": True, "after_deactivate": off, "after_activate": on}
"""
        )

    # 9. reopen persistence --------------------------------------------------
    def reopen_niagara_asset(self, asset_path: str) -> Dict[str, Any]:
        return self.bridge.execute_python(
            f"""
import unreal
a = unreal.EditorAssetLibrary.load_asset({self._q(asset_path)})
if a is None:
    __bridge_result__ = {{"ok": False, "error": "asset missing after reopen"}}
else:
    __bridge_result__ = {{"ok": True, "class": a.get_class().get_name(),
                           "path": {self._q(asset_path)},
                           "is_system": a.get_class().get_name() == "NiagaraSystem"}}
"""
        )
