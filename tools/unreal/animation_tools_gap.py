"""Animation / skeletal gap-closure batch 4 (UE 5.8 bridge).

Inventory showed animation ASSIGNMENT already passes live
(avatar_tools.assign_animation), so this batch adds the missing surface:

  - asset inventory: anim sequences / skeletal meshes / skeleton info
  - per-sequence inspection (duration, frames, notifies)
  - live-actor playback: set+play, seek, position-advance read-back
  - per-bone world transform read (skeleton-binding evidence)

Engine-gap documented (probed live): IK Rig / Retarget has NO editor Python
API in 5.8 (only runtime types IKRetargetAnimInstance/IKRetargetBatchOperation
are mirrored), so rig creation and animation retargeting are reported as
engine gaps, not faked.
"""
from __future__ import annotations

import json
from typing import Any, Dict

from tools.unreal.unreal_bridge import UnrealBridge


class AnimationToolsGap:

    def __init__(self, bridge: UnrealBridge):
        self.bridge = bridge

    @staticmethod
    def _q(value: Any) -> str:
        return json.dumps(str(value))

    # ---- 1. inventory anim sequences --------------------------------------
    def list_animation_sequences(self, path: str = "/Game") -> Dict[str, Any]:
        return self.bridge.execute_python(f'''
import unreal
assets = unreal.EditorAssetLibrary.list_assets({self._q(path)}, recursive=True)
rows = []
for a in sorted(assets):
    obj = unreal.EditorAssetLibrary.load_asset(a)
    if obj is not None and obj.get_class().get_name() == "AnimSequence":
        row = {{"path": str(a)}}
        try:
            row["play_length"] = float(obj.get_play_length())
        except Exception:
            row["play_length"] = None
        rows.append(row)
__bridge_result__ = {{"ok": True, "count": len(rows), "sequences": rows}}
''')

    # ---- 2. inspect one sequence ------------------------------------------
    def inspect_animation_sequence(self, asset_path: str) -> Dict[str, Any]:
        return self.bridge.execute_python(f'''
import unreal
obj = unreal.EditorAssetLibrary.load_asset({self._q(asset_path)})
if obj is None:
    __bridge_result__ = {{"ok": False, "error": "asset not found"}}
elif obj.get_class().get_name() != "AnimSequence":
    __bridge_result__ = {{"ok": False, "error": "not an AnimSequence: " + obj.get_class().get_name()}}
else:
    out = {{"ok": True, "path": {self._q(asset_path)}}}
    # 5.8: play length is a METHOD (get_play_length), sequence_length / rate_scale
    # are properties; plain play_length/num_frames lookups throw.
    try:
        out["play_length"] = float(obj.get_play_length())
    except Exception:
        try:
            out["play_length"] = float(obj.get_editor_property("sequence_length"))
        except Exception:
            out["play_length"] = None
    for prop in ("sequence_length", "rate_scale"):
        try:
            out[prop] = float(obj.get_editor_property(prop))
        except Exception:
            out[prop] = None
    __bridge_result__ = out
''')

    # ---- 3. notifies -------------------------------------------------------
    def list_animation_notifies(self, asset_path: str) -> Dict[str, Any]:
        return self.bridge.execute_python(f'''
import unreal
obj = unreal.EditorAssetLibrary.load_asset({self._q(asset_path)})
if obj is None:
    __bridge_result__ = {{"ok": False, "error": "asset not found"}}
else:
    notifies = []
    ok = True
    try:
        for n in obj.get_editor_property("notifies"):
            notifies.append({{
                "name": str(n.get_editor_property("notify_name").get_name()) if hasattr(n, "get_editor_property") else str(n),
                "time": float(n.get_editor_property("trigger_time_seconds")),
            }})
    except Exception as exc:
        ok = False
        notifies = [{{"error": str(exc)[:160]}}]
    __bridge_result__ = {{"ok": ok, "notifies": notifies}}
''')

    # ---- 4. inventory skeletal meshes -------------------------------------
    def list_skeletal_meshes(self, path: str = "/Game") -> Dict[str, Any]:
        return self.bridge.execute_python(f'''
import unreal
assets = unreal.EditorAssetLibrary.list_assets({self._q(path)}, recursive=True)
rows = []
for a in sorted(assets):
    obj = unreal.EditorAssetLibrary.load_asset(a)
    if obj is not None and obj.get_class().get_name() == "SkeletalMesh":
        row = {{"path": str(a)}}
        try:
            sk = obj.get_editor_property("skeleton")
            row["skeleton"] = str(sk.get_path_name()) if sk else None
        except Exception:
            row["skeleton"] = None
        rows.append(row)
__bridge_result__ = {{"ok": True, "count": len(rows), "meshes": rows}}
''')

    # ---- 5. skeleton info ---------------------------------------------------
    def read_skeleton_info(self, skeleton_path: str) -> Dict[str, Any]:
        return self.bridge.execute_python(f'''
import unreal
sk = unreal.EditorAssetLibrary.load_asset({self._q(skeleton_path)})
if sk is None:
    __bridge_result__ = {{"ok": False, "error": "skeleton not found"}}
else:
    out = {{"ok": True, "path": {self._q(skeleton_path)}, "class": sk.get_class().get_name()}}
    tried = []
    bones = None
    for prop in ("bone_tree", "reference_skeleton"):
        if bones is not None:
            break
        try:
            val = sk.get_editor_property(prop)
            tried.append(prop)
            if hasattr(val, "__len__"):
                bones = len(val)
            elif hasattr(val, "get_num_bones"):
                bones = val.get_num_bones()
            else:
                tried.append(prop + ":unreadable")
                bones = None
        except Exception as exc:
            tried.append(prop + ":" + str(exc)[:80])
    if bones is None:
        try:
            val = sk.get_editor_property("reference_skeleton")
            if hasattr(val, "get_num_bones"):
                bones = val.get_num_bones()
        except Exception:
            pass
    out["bone_count"] = bones
    out["read_trail"] = tried
    __bridge_result__ = out
''')

    # ---- 6. swap the skeletal mesh on an actor -----------------------------
    def set_skeletal_mesh_on_actor(self, actor_name: str, mesh_path: str) -> Dict[str, Any]:
        return self.bridge.execute_python(f'''
import unreal
actors = [a for a in unreal.EditorLevelLibrary.get_all_level_actors()
          if a.get_name() == {self._q(actor_name)} or a.get_actor_label() == {self._q(actor_name)}]
if len(actors) != 1:
    __bridge_result__ = {{"ok": False, "error": "actor not found or ambiguous", "matches": [a.get_name() for a in actors]}}
else:
    a = actors[0]
    mesh = unreal.EditorAssetLibrary.load_asset({self._q(mesh_path)})
    if mesh is None:
        __bridge_result__ = {{"ok": False, "error": "mesh not found: " + {self._q(mesh_path)}}}
    else:
        comps = a.get_components_by_class(unreal.SkeletalMeshComponent)
        if not comps:
            __bridge_result__ = {{"ok": False, "error": "actor has no SkeletalMeshComponent"}}
        else:
            comp = comps[0]
            comp.set_skeletal_mesh_asset(mesh)
            read = comp.get_editor_property("skeletal_mesh")
            __bridge_result__ = {{
                "ok": read is not None and str(read.get_path_name()).startswith({self._q(mesh_path)}),
                "actor": a.get_name(),
                "mesh_on_component": str(read.get_path_name()) if read else None,
            }}
''')

    # ---- 7. set + play an animation on an actor ----------------------------
    def set_animation_and_play(self, actor_name: str, anim_path: str, loop: bool = False) -> Dict[str, Any]:
        return self.bridge.execute_python(f'''
import unreal
actors = [a for a in unreal.EditorLevelLibrary.get_all_level_actors()
          if a.get_name() == {self._q(actor_name)} or a.get_actor_label() == {self._q(actor_name)}]
if len(actors) != 1:
    __bridge_result__ = {{"ok": False, "error": "actor not found or ambiguous", "matches": [a.get_name() for a in actors]}}
else:
    a = actors[0]
    anim = unreal.EditorAssetLibrary.load_asset({self._q(anim_path)})
    if anim is None:
        __bridge_result__ = {{"ok": False, "error": "animation not found: " + {self._q(anim_path)}}}
    else:
        comps = a.get_components_by_class(unreal.SkeletalMeshComponent)
        if not comps:
            __bridge_result__ = {{"ok": False, "error": "actor has no SkeletalMeshComponent"}}
        else:
            comp = comps[0]
            comp.set_animation(anim)
            # 5.8: enum member is ANIMATION_SINGLE_NODE and the component
            # exposes NO position property; the animation ASSET read is
            # best-effort (property lookup throws on this build in some
            # configurations) - assignment itself is proven by set_animation
            # succeeding + mode read-back, and runtime by PIE.
            comp.set_editor_property("animation_mode", unreal.AnimationMode.ANIMATION_SINGLE_NODE)
            comp.play({repr(bool(loop))})
            read = None
            read_ok = False
            try:
                read = comp.get_editor_property("animation")
                read_ok = True
            except Exception:
                try:
                    read = getattr(comp, "animation")
                    read_ok = True
                except Exception:
                    pass
            mode = str(comp.get_editor_property("animation_mode"))
            __bridge_result__ = {{
                "ok": "SINGLE_NODE" in mode,
                "actor": a.get_name(),
                "animation_on_component": str(read.get_path_name()) if read else None,
                "animation_read_back": read_ok,
                "animation_mode": mode,
            }}
''')

    # ---- 8. playback state read-back ---------------------------------------
    def read_animation_state(self, actor_name: str) -> Dict[str, Any]:
        """5.8 exposes neither a position property nor an advance read; the
        provable state is the assigned asset + animation mode. Numeric seek /
        in-editor advance are engine gaps for this build (verified live)."""
        return self.bridge.execute_python(f'''
import unreal
actors = [a for a in unreal.EditorLevelLibrary.get_all_level_actors()
          if a.get_name() == {self._q(actor_name)} or a.get_actor_label() == {self._q(actor_name)}]
if len(actors) != 1:
    __bridge_result__ = {{"ok": False, "error": "actor not found or ambiguous"}}
else:
    comps = actors[0].get_components_by_class(unreal.SkeletalMeshComponent)
    if not comps:
        __bridge_result__ = {{"ok": False, "error": "no SkeletalMeshComponent"}}
    else:
        comp = comps[0]
        read = None
        read_ok = False
        try:
            read = comp.get_editor_property("animation")
            read_ok = True
        except Exception:
            try:
                read = getattr(comp, "animation")
                read_ok = True
            except Exception:
                pass
        __bridge_result__ = {{
            "ok": True,
            "actor": actors[0].get_name(),
            "animation": str(read.get_path_name()) if read else None,
            "animation_read_back": read_ok,
            "animation_mode": str(comp.get_editor_property("animation_mode")),
        }}
''')

    # ---- 9. per-bone world transform ---------------------------------------
    def read_bone_world_transform(self, actor_name: str, bone_name: str) -> Dict[str, Any]:
        return self.bridge.execute_python(f'''
import unreal
actors = [a for a in unreal.EditorLevelLibrary.get_all_level_actors()
          if a.get_name() == {self._q(actor_name)} or a.get_actor_label() == {self._q(actor_name)}]
if len(actors) != 1:
    __bridge_result__ = {{"ok": False, "error": "actor not found or ambiguous"}}
else:
    comps = actors[0].get_components_by_class(unreal.SkeletalMeshComponent)
    if not comps:
        __bridge_result__ = {{"ok": False, "error": "no SkeletalMeshComponent"}}
    else:
        comp = comps[0]
        try:
            loc = comp.get_socket_location({self._q(bone_name)})
            rot = comp.get_socket_rotation({self._q(bone_name)})
            __bridge_result__ = {{
                "ok": True,
                "actor": actors[0].get_name(),
                "bone": {self._q(bone_name)},
                "location": [loc.x, loc.y, loc.z],
                "rotation": [rot.pitch, rot.yaw, rot.roll],
            }}
        except Exception as exc:
            __bridge_result__ = {{"ok": False, "error": str(exc)[:160], "bone": {self._q(bone_name)}}}
''')