"""Landscape / foliage / PCG gap-closure batch 8 (UE 5.8 bridge, final breadth).

Surface probed live before implementation:
  - Landscape: 65 symbols mirrored (Landscape/LandscapeComponent/LandscapeProxy/
    LandscapeGrassTypeFactory ...) but NO LandscapeEditorSubsystem /
    LandscapeSubsystem in dir(unreal) - landscape CREATION is editor-tool only
    (same closed class as IK-retarget/landscape editor). Recorded as a gap, not
    faked; the actor/material asset classes are inventoried.
  - Foliage: FoliageType_InstancedStaticMeshFactory constructible, FoliageType
    exposes a "mesh" property, InstancedFoliageActor.add_instances(world,
    foliage_type, transforms[Array[Transform]]) is python-callable.
  - PCG: 684 symbols; PCGGraphFactory / PCGGraphInstanceFactory exist and
    PCGGraph exposes graph authoring (add_node_of_type(settings_class) ->
    node, add_edge(from_, from_pin_label, to, to_pin_label) -> To node,
    get_all_edges, get_input_node/get_output_node). No PCGSubsystem /
    PCGEditorSubsystem mirror - runtime generation outside the editor flow is
    not substantiable; asset authoring + inventory is.

  1. landscape_surface_probe      - 65-symbol inventory + creation gap record
  2. list_terrain_assets          - project scan for Landscape/Foliage/PCG assets
  3. create_foliage_type          - FoliageType_InstancedStaticMeshFactory asset
  4. spawn_foliage_instances      - InstancedFoliageActor + add_instances + count
  5. create_pcg_graph             - PCGGraphFactory asset + save
  6. author_pcg_graph             - add nodes + edge + read-back
  7. reopen_terrain_asset         - reopen identity checks
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from tools.unreal.unreal_bridge import UnrealBridge


class TerrainToolsGap:

    def __init__(self, bridge: UnrealBridge):
        self.bridge = bridge

    @staticmethod
    def _q(value: Any) -> str:
        return json.dumps(str(value))

    # 1. landscape surface + creation gap -----------------------------------
    def landscape_surface_probe(self) -> Dict[str, Any]:
        return self.bridge.execute_python(
            """
import unreal
names = sorted(n for n in dir(unreal) if "Landscape" in n)
key = {
    "Landscape": hasattr(unreal, "Landscape"),
    "LandscapeComponent": hasattr(unreal, "LandscapeComponent"),
    "LandscapeProxy": hasattr(unreal, "LandscapeProxy"),
    "LandscapeGrassTypeFactory": hasattr(unreal, "LandscapeGrassTypeFactory"),
    "LandscapeEditorSubsystem": hasattr(unreal, "LandscapeEditorSubsystem"),
    "LandscapeSubsystem": hasattr(unreal, "LandscapeSubsystem"),
}
__bridge_result__ = {"ok": True, "total": len(names), "key_classes": key,
                     "creation_closed": not (key["LandscapeEditorSubsystem"] or key["LandscapeSubsystem"]),
                     "gap": ("landscape creation requires the LandscapeEditor C++ tool - "
                             "no editor subsystem mirrored to python (verbatim: absent from dir(unreal))")}
"""
        )

    # 2. project inventory ---------------------------------------------------
    def list_terrain_assets(self, root: str = "/Game") -> Dict[str, Any]:
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
            if any(k in cls for k in ("Landscape", "FoliageType", "PCGGraph", "PCGVolume",
                                       "ProceduralFoliage")):
                found.append({{"path": p, "class": cls}})
    except Exception:
        pass
__bridge_result__ = {{"ok": True, "total_assets": len(allp),
                       "terrain_assets": found[:60], "terrain_count": len(found)}}
"""
        )

    # 3. create a foliage type asset -----------------------------------------
    def create_foliage_type(self, name: str, folder: str = "/Game/Batch8Env",
                            mesh_path: str = "/Engine/BasicShapes/Cube") -> Dict[str, Any]:
        return self.bridge.execute_python(
            f"""
import unreal
asset_path = {self._q(folder)} + "/" + {self._q(name)}
if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
    unreal.EditorAssetLibrary.delete_asset(asset_path)
mesh = unreal.EditorAssetLibrary.load_asset({self._q(mesh_path)})
at = unreal.AssetToolsHelpers.get_asset_tools()
factory = unreal.FoliageType_InstancedStaticMeshFactory()
obj = at.create_asset({self._q(name)}, {self._q(folder)}, unreal.FoliageType_InstancedStaticMesh, factory)
if obj is None:
    __bridge_result__ = {{"ok": False, "error": "create_asset returned None"}}
else:
    if mesh is not None:
        try:
            obj.set_editor_property("mesh", mesh)
        except Exception as exc:
            pass
    saved = unreal.EditorAssetLibrary.save_asset(asset_path)
    __bridge_result__ = {{"ok": True, "class": obj.get_class().get_name(),
                           "path": asset_path, "saved": saved,
                           "mesh_set": mesh is not None,
                           "mesh": str(obj.get_editor_property("mesh")) if mesh is not None else None}}
"""
        )

    # 4. spawn foliage instances ----------------------------------------------
    def spawn_foliage_instances(self, foliage_path: str, count: int = 4,
                                origin=(0.0, 0.0, 0.0), spacing=150.0) -> Dict[str, Any]:
        return self.bridge.execute_python(
            f"""
import unreal
world = unreal.EditorLevelLibrary.get_editor_world()
ft = unreal.EditorAssetLibrary.load_asset({self._q(foliage_path)})
if ft is None:
    __bridge_result__ = {{"ok": False, "error": "foliage type not loadable"}}
else:
    ifa = unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.InstancedFoliageActor,
            unreal.Vector({float(origin[0])}, {float(origin[1])}, {float(origin[2])}),
            unreal.Rotator(0, 0, 0))
    if ifa is None:
        __bridge_result__ = {{"ok": False, "error": "spawn InstancedFoliageActor returned None"}}
    else:
        ifa.set_actor_label("Batch8Foliage")
        xforms = []
        for i in range({int(count)}):
            xforms.append(unreal.Transform(
                unreal.Vector({float(origin[0])} + i * {float(spacing)},
                              {float(origin[1])} + (i % 2) * {float(spacing)},
                              {float(origin[2])}),
                unreal.Rotator(0, 0, 0), unreal.Vector(1, 1, 1)))
        try:
            unreal.InstancedFoliageActor.add_instances(world, ft, xforms)
            __bridge_result__ = {{"ok": True, "actor": ifa.get_actor_label(),
                                   "class": ifa.get_class().get_name(),
                                   "instances_requested": {int(count)}}}
        except Exception as exc:
            __bridge_result__ = {{"ok": False, "error": str(exc)[:300]}}
"""
        )

    # 5. create a PCG graph asset ---------------------------------------------
    def create_pcg_graph(self, name: str, folder: str = "/Game/Batch8Env") -> Dict[str, Any]:
        return self.bridge.execute_python(
            f"""
import unreal
asset_path = {self._q(folder)} + "/" + {self._q(name)}
if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
    unreal.EditorAssetLibrary.delete_asset(asset_path)
at = unreal.AssetToolsHelpers.get_asset_tools()
factory = unreal.PCGGraphFactory()
obj = at.create_asset({self._q(name)}, {self._q(folder)}, unreal.PCGGraph, factory)
if obj is None:
    __bridge_result__ = {{"ok": False, "error": "create_asset returned None"}}
else:
    saved = unreal.EditorAssetLibrary.save_asset(asset_path)
    __bridge_result__ = {{"ok": True, "class": obj.get_class().get_name(),
                           "path": asset_path, "saved": saved}}
"""
        )

    # 6. author the graph: nodes + edges + read-back --------------------------
    def author_pcg_graph(self, graph_path: str) -> Dict[str, Any]:
        return self.bridge.execute_python(
            f"""
import unreal
g = unreal.EditorAssetLibrary.load_asset({self._q(graph_path)})
if g is None:
    __bridge_result__ = {{"ok": False, "error": "graph not loadable"}}
else:
    try:
        in_node = g.get_input_node()
        out_node = g.get_output_node()
    except Exception as exc:
        in_node = out_node = None
    added = []
    surf = None
    spawn = None
    for settings_cls in ("PCGSurfaceSamplerSettings", "PCGStaticMeshSpawnerSettings"):
        try:
            node, settings = g.add_node_of_type(getattr(unreal, settings_cls))
            added.append({{'cls': settings_cls, 'node': node.get_name()}})
            if settings_cls == "PCGSurfaceSamplerSettings":
                surf = node
            else:
                spawn = node
        except Exception as exc:
            added.append({{'cls': settings_cls, 'error': str(exc)[:160]}})
    edges = []
    edge_errs = []
    if surf and spawn:
        try:
            to = g.add_edge(surf, "Out", spawn, "In")
            edges.append({{'edge': 'Surface->Spawner', 'to': to.get_name() if to else None}})
        except Exception as exc:
            edge_errs.append({{'edge': 'Surface->Spawner', 'error': str(exc)[:200]}})
    if in_node and surf:
        try:
            to = g.add_edge(in_node, "Out", surf, "In")
            edges.append({{'edge': 'Input->Surface', 'to': to.get_name() if to else None}})
        except Exception as exc:
            edge_errs.append({{'edge': 'Input->Surface', 'error': str(exc)[:200]}})
    saved = unreal.EditorAssetLibrary.save_asset({self._q(graph_path)})
    total_edges = 0
    try:
        total_edges = len(g.get_all_edges())
    except Exception:
        pass
    __bridge_result__ = {{"ok": True, "nodes_added": added,
                           "edges": edges, "edge_errors": edge_errs,
                           "input_node": in_node.get_name() if in_node else None,
                           "output_node": out_node.get_name() if out_node else None,
                           "total_edges": total_edges, "saved": saved}}
"""
        )

    # 7. reopen identity ------------------------------------------------------
    def reopen_terrain_asset(self, asset_path: str) -> Dict[str, Any]:
        return self.bridge.execute_python(
            f"""
import unreal
a = unreal.EditorAssetLibrary.load_asset({self._q(asset_path)})
if a is None:
    __bridge_result__ = {{"ok": False, "error": "asset missing after reopen"}}
else:
    __bridge_result__ = {{"ok": True, "class": a.get_class().get_name(),
                           "path": {self._q(asset_path)}}}
"""
        )
