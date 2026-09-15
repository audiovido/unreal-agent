"""World / actor / level gap-closure batch 2 (UE 5.8 bridge).

Fills gaps AROUND the existing live-proven surface WITHOUT reimplementing it:

  EXISTS (not duplicated here): spawn_actor / get_actor / move|rotate|scale_actor
  / delete_actor / list_level_actors / save_level(+save-as) / open_map /
  get_current_level / is_level_dirty / list_assets (unreal_bridge.py)

  NEW in this batch:
    1. list_level_actor_details  - full table: name/label/class/transform/tags
    2. set_actor_transform       - one-shot location+rotation+scale
    3. rename_actor              - internal name + label rename, collision-safe
    4. set_actor_tags            - set+read-back editor tags
    5. bulk_spawn                - N actors on a grid from one spec
    6. world_summary             - map identity / actor count / class histogram
    7. delete_actors_by_class    - bulk destroy by actor class name
"""
from __future__ import annotations

import json
from typing import Any, Dict

from tools.unreal.unreal_bridge import UnrealBridge


class WorldToolsGap:

    def __init__(self, bridge: UnrealBridge):
        self.bridge = bridge

    @staticmethod
    def _q(value: Any) -> str:
        return json.dumps(str(value))

    # ---- 1. full level-actor query table ----------------------------------
    def list_level_actor_details(self) -> Dict[str, Any]:
        return self.bridge.execute_python(f'''
actors = unreal.EditorLevelLibrary.get_all_level_actors()
if actors is None:
    __bridge_result__ = {{"ok": False, "error": "no editor world"}}
else:
    rows = []
    for a in actors:
        loc = a.get_actor_location()
        rot = a.get_actor_rotation()
        scl = a.get_actor_scale3d()
        tags = []
        try:
            tags = [str(t) for t in a.get_editor_property("tags")]
        except Exception:
            pass
        rows.append({{
            "name": str(a.get_name()),
            "label": str(a.get_actor_label()),
            "class": str(a.get_class().get_name()),
            "location": [loc.x, loc.y, loc.z],
            "rotation": [rot.pitch, rot.yaw, rot.roll],
            "scale": [scl.x, scl.y, scl.z],
            "tags": tags,
        }})
    __bridge_result__ = {{"ok": True, "actor_count": len(rows), "actors": rows}}
''')

    # ---- 2. one-shot transform ---------------------------------------------
    def set_actor_transform(self, actor_name: str, location=None, rotation=None, scale=None) -> Dict[str, Any]:
        loc = json.dumps(location) if location is not None else "None"
        rot = json.dumps(rotation) if rotation is not None else "None"
        scl = json.dumps(scale) if scale is not None else "None"
        return self.bridge.execute_python(f'''
actors = unreal.EditorLevelLibrary.get_all_level_actors()
matches = [a for a in actors if a.get_name() == {self._q(actor_name)} or a.get_actor_label() == {self._q(actor_name)}]
if len(matches) != 1:
    __bridge_result__ = {{"ok": False, "error": "actor not found or ambiguous: " + {self._q(actor_name)}, "matches": [a.get_name() for a in matches]}}
else:
    a = matches[0]
    loc = {loc}
    rot = {rot}
    scl = {scl}
    if loc is not None:
        a.set_actor_location(unreal.Vector(loc[0], loc[1], loc[2]), False, False)
    if rot is not None:
        a.set_actor_rotation(unreal.Rotator(rot[0], rot[1], rot[2]), False)
    if scl is not None:
        a.set_actor_scale3d(unreal.Vector(scl[0], scl[1], scl[2]))
    out = a.get_actor_location(), a.get_actor_rotation(), a.get_actor_scale3d()
    __bridge_result__ = {{
        "ok": True,
        "name": a.get_name(),
        "location": [out[0].x, out[0].y, out[0].z],
        "rotation": [out[1].pitch, out[1].yaw, out[1].roll],
        "scale": [out[2].x, out[2].y, out[2].z],
    }}
''')

    # ---- 3. rename actor ---------------------------------------------------
    def rename_actor(self, actor_name: str, new_name: str) -> Dict[str, Any]:
        return self.bridge.execute_python(f'''
actors = unreal.EditorLevelLibrary.get_all_level_actors()
matches = [a for a in actors if a.get_name() == {self._q(actor_name)} or a.get_actor_label() == {self._q(actor_name)}]
if len(matches) != 1:
    __bridge_result__ = {{"ok": False, "error": "actor not found or ambiguous: " + {self._q(actor_name)}, "matches": [a.get_name() for a in matches]}}
else:
    a = matches[0]
    collision = [b for b in actors if b is not a and (b.get_name() == {self._q(new_name)} or b.get_actor_label() == {self._q(new_name)})]
    if collision:
        __bridge_result__ = {{"ok": False, "error": "name already used by another actor", "collides_with": [c.get_name() for c in collision]}}
    else:
        a.rename({self._q(new_name)})
        a.set_actor_label({self._q(new_name)})
        __bridge_result__ = {{
            "ok": True,
            "name": a.get_name(),
            "label": a.get_actor_label(),
        }}
''')

    # ---- 4. actor tags -----------------------------------------------------
    def set_actor_tags(self, actor_name: str, tags) -> Dict[str, Any]:
        tag_list = json.dumps([str(t) for t in tags])
        return self.bridge.execute_python(f'''
actors = unreal.EditorLevelLibrary.get_all_level_actors()
matches = [a for a in actors if a.get_name() == {self._q(actor_name)} or a.get_actor_label() == {self._q(actor_name)}]
if len(matches) != 1:
    __bridge_result__ = {{"ok": False, "error": "actor not found or ambiguous: " + {self._q(actor_name)}, "matches": [a.get_name() for a in matches]}}
else:
    a = matches[0]
    wanted = {tag_list}
    try:
        a.set_editor_property("tags", [unreal.Name(t) for t in wanted])
    except Exception as exc:
        __bridge_result__ = {{"ok": False, "error": str(exc)}}
    else:
        read = [str(t) for t in a.get_editor_property("tags")]
        __bridge_result__ = {{"ok": sorted(read) == sorted(wanted), "tags": read}}
''')

    # ---- 5. bulk spawn -----------------------------------------------------
    def bulk_spawn(self, class_name: str = "StaticMeshActor", count: int = 1,
                   origin=(0.0, 0.0, 0.0), spacing=(200.0, 200.0, 0.0),
                   name_prefix: str = "Spawner", scale=None,
                   mesh_asset: str | None = None) -> Dict[str, Any]:
        if count < 1:
            return {"ok": False, "error": "count must be >= 1", "created": 0}
        origin = json.dumps([float(v) for v in origin])
        spacing = json.dumps([float(v) for v in spacing])
        scl = json.dumps([float(v) for v in scale]) if scale is not None else "None"
        mesh = self._q(mesh_asset) if mesh_asset else "None"
        return self.bridge.execute_python(f'''
origin = {origin}
spacing = {spacing}
scl = {scl}
mesh = {mesh}
cls = getattr(unreal, {self._q(class_name)}, None)
if cls is None:
    __bridge_result__ = {{"ok": False, "error": "unknown class: " + {self._q(class_name)}, "created": []}}
else:
    created = []
    errors = []
    for i in range({int(count)}):
        col = i % 5
        row = i // 5
        loc = unreal.Vector(origin[0] + col * spacing[0], origin[1] + row * spacing[1], origin[2] + row * spacing[2])
        try:
            actor = unreal.EditorLevelLibrary.spawn_actor_from_class(cls, loc, unreal.Rotator(0.0, 0.0, 0.0))
            if actor is None:
                errors.append(str(i) + ":spawn returned None")
                continue
            # Collision-safe rename: UObject.Rename FATAL-checks when the new
            # name is already taken, so compute a free suffix first.
            taken = set(a.get_name() for a in unreal.EditorLevelLibrary.get_all_level_actors())
            suffix = i
            base = {self._q(name_prefix)}
            while base + str(suffix) in taken:
                suffix += 1
            actor.rename(base + str(suffix))
            actor.set_actor_label(base + str(suffix))
            if scl is not None:
                actor.set_actor_scale3d(unreal.Vector(scl[0], scl[1], scl[2]))
            if mesh is not None:
                comps = actor.get_components_by_class(unreal.StaticMeshComponent)
                if comps:
                    comps[0].set_editor_property("static_mesh", unreal.EditorAssetLibrary.load_asset(mesh))
            created.append({{"index": i, "name": actor.get_name(), "location": [loc.x, loc.y, loc.z]}})
        except Exception as exc:
            errors.append(str(i) + ":" + str(exc))
__bridge_result__ = {{"ok": len(errors) == 0 and len(created) == {int(count)}, "created": created, "errors": errors}}
''')

    # ---- 6. world summary --------------------------------------------------
    def world_summary(self) -> Dict[str, Any]:
        return self.bridge.execute_python(f'''
world = unreal.EditorLevelLibrary.get_editor_world()
if world is None:
    __bridge_result__ = {{"ok": False, "error": "no editor world"}}
else:
    actors = unreal.EditorLevelLibrary.get_all_level_actors() or []
    hist = {{}}
    minv = [10 ** 9] * 3
    maxv = [-10 ** 9] * 3
    for a in actors:
        c = a.get_class().get_name()
        hist[c] = hist.get(c, 0) + 1
        loc = a.get_actor_location()
        for i in range(3):
            v = [loc.x, loc.y, loc.z][i]
            minv[i] = min(minv[i], v)
            maxv[i] = max(maxv[i], v)
    __bridge_result__ = {{
        "ok": True,
        "map": str(world.get_path_name()),
        "actor_count": len(actors),
        "class_histogram": hist,
        "bounds": {{"min": minv if actors else None, "max": maxv if actors else None}},
    }}
''')

    # ---- 7. bulk delete by class -------------------------------------------
    def delete_actors_by_class(self, class_name: str) -> Dict[str, Any]:
        return self.bridge.execute_python(f'''
actors = unreal.EditorLevelLibrary.get_all_level_actors() or []
targets = [a for a in actors if a.get_class().get_name() == {self._q(class_name)}]
removed = []
for a in targets:
    try:
        unreal.EditorLevelLibrary.destroy_actor(a)
        removed.append(a.get_name())
    except Exception as exc:
        removed.append(a.get_name() + ":failed:" + str(exc))
remaining = [a for a in unreal.EditorLevelLibrary.get_all_level_actors() or [] if a.get_class().get_name() == {self._q(class_name)}]
__bridge_result__ = {{"ok": len(remaining) == 0, "removed": removed, "remaining": len(remaining)}}
''')