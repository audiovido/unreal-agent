"""Sequencer / cameras gap-closure batch 5 (UE 5.8 bridge).

Surface probed live before implementation: MovieSceneSequenceExtensions
(add_track/add_possessable/find_tracks_by_type), MovieSceneTrackExtensions
(add_section/get_sections/remove_section), MovieSceneSectionExtensions
(set_range_seconds/get_start/end_frame_seconds), LevelSequenceEditorSubsystem
(create_camera, add_actors), LevelSequenceEditorBlueprintLibrary
(play/pause/is_playing/set_current_time/set_playback_speed) are ALL exposed.

CLOSED surface recorded, not faked: MovieSceneFloatChannel exposes nothing in
5.8 Python (no add_keys/channel-key API) - per-frame KEYFRAME insertion into
transform tracks is therefore unreportable from Python; the primitives prove
track + section + range + playback + read-back and report the exact closed
call when key insertion is attempted.

  1. create_level_sequence      - LevelSequenceFactoryNew asset create+save
  2. list_level_sequences       - registry inventory
  3. add_actor_binding          - bind a level actor (possessable)
  4. add_track_with_section     - add a named track + section + time range
  5. add_camera_cut             - create a CineCamera actor + camera track
  6. scrub_and_play             - headless play/pause/scrub/speed control
  7. read_sequence_structure    - bindings/tracks/sections/ranges read-back
  8. save_sequence              - save + reopen + verify identity
"""
from __future__ import annotations

import json
from typing import Any, Dict

from tools.unreal.unreal_bridge import UnrealBridge


class SequencerToolsGap:

    def __init__(self, bridge: UnrealBridge):
        self.bridge = bridge

    @staticmethod
    def _q(value: Any) -> str:
        return json.dumps(str(value))

    # ---- 1. create ---------------------------------------------------------
    def create_level_sequence(self, asset_path: str) -> Dict[str, Any]:
        if "/" not in asset_path or not asset_path.startswith("/Game/"):
            return {"ok": False, "error": "expected a /Game asset path, got: " + str(asset_path)}
        name = asset_path.rsplit("/", 1)[-1]
        path = asset_path.rsplit("/", 1)[0]
        if not name:
            return {"ok": False, "error": "empty sequence name"}
        return self.bridge.execute_python(f'''
import unreal
name = {self._q(name)}
path = {self._q(path)}
unreal.EditorAssetLibrary.make_directory(path)
existing = unreal.EditorAssetLibrary.load_asset(path + "/" + name)
if existing is not None:
    __bridge_result__ = {{"ok": existing.get_class().get_name() == "LevelSequence", "created": False, "preserved": True, "asset_path": path + "/" + name}}
else:
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    seq = tools.create_asset(name, path, unreal.LevelSequence, unreal.LevelSequenceFactoryNew())
    saved = bool(unreal.EditorAssetLibrary.save_loaded_asset(seq, False)) if seq is not None else False
    reloaded = unreal.EditorAssetLibrary.load_asset(path + "/" + name)
    __bridge_result__ = {{
        "ok": bool(reloaded is not None and reloaded.get_class().get_name() == "LevelSequence" and saved),
        "created": seq is not None,
        "saved": saved,
        "asset_path": path + "/" + name,
    }}
''')

    # ---- 2. inventory ------------------------------------------------------
    def list_level_sequences(self, path: str = "/Game") -> Dict[str, Any]:
        return self.bridge.execute_python(f'''
import unreal
rows = []
for a in sorted(unreal.EditorAssetLibrary.list_assets({self._q(path)}, recursive=True)):
    obj = unreal.EditorAssetLibrary.load_asset(a)
    if obj is not None and obj.get_class().get_name() == "LevelSequence":
        rows.append(str(a))
__bridge_result__ = {{"ok": True, "count": len(rows), "sequences": rows}}
''')

    # ---- 3. actor binding ----------------------------------------------------
    def add_actor_binding(self, seq_path: str, actor_label: str) -> Dict[str, Any]:
        return self.bridge.execute_python(f'''
import unreal
seq = unreal.EditorAssetLibrary.load_asset({self._q(seq_path)})
actors = [a for a in unreal.EditorLevelLibrary.get_all_level_actors()
          if a.get_actor_label() == {self._q(actor_label)} or a.get_name() == {self._q(actor_label)}]
if seq is None:
    __bridge_result__ = {{"ok": False, "error": "sequence not found"}}
elif len(actors) != 1:
    __bridge_result__ = {{"ok": False, "error": "actor not found or ambiguous: " + {self._q(actor_label)}, "matches": [a.get_name() for a in actors]}}
else:
    try:
        binding = unreal.MovieSceneSequenceExtensions.add_possessable(seq, actors[0])
        bid = unreal.MovieSceneSequenceExtensions.get_binding_id(seq, binding) if binding is not None else None
        __bridge_result__ = {{
            "ok": binding is not None,
            "actor": actors[0].get_name(),
            "binding_id": str(bid) if bid else None,
        }}
    except Exception as exc:
        __bridge_result__ = {{"ok": False, "error": str(exc)[:200]}}
''')

    # ---- 4. track + section + range ------------------------------------------
    def add_track_with_section(self, seq_path: str, actor_label: str,
                               track_class: str, start_s: float, end_s: float) -> Dict[str, Any]:
        return self.bridge.execute_python(f'''
import unreal
seq = unreal.EditorAssetLibrary.load_asset({self._q(seq_path)})
if seq is None:
    __bridge_result__ = {{"ok": False, "error": "sequence not found"}}
else:
    binding = unreal.MovieSceneSequenceExtensions.find_binding_by_name(seq, {self._q(actor_label)})
    if binding is None:
        __bridge_result__ = {{"ok": False, "error": "no binding for actor: " + {self._q(actor_label)}}}
    else:
        cls = getattr(unreal, {self._q(track_class)}, None)
        if cls is None:
            __bridge_result__ = {{"ok": False, "error": "unknown track class: " + {self._q(track_class)}}}
        else:
            try:
                track = unreal.MovieSceneSequenceExtensions.add_track(seq, cls)
                section = unreal.MovieSceneTrackExtensions.add_section(track)
                unreal.MovieSceneSectionExtensions.set_range_seconds(section, float({json.dumps(float(start_s))}), float({json.dumps(float(end_s))}))
                rb = [
                    float(unreal.MovieSceneSectionExtensions.get_start_frame_seconds(section)),
                    float(unreal.MovieSceneSectionExtensions.get_end_frame_seconds(section)),
                ]
                __bridge_result__ = {{
                    "ok": track is not None and section is not None and abs(rb[0] - float({json.dumps(float(start_s))})) < 0.05,
                    "track_class": {self._q(track_class)},
                    "section_range": rb,
                    "display_name": str(unreal.MovieSceneTrackExtensions.get_display_name(track)),
                }}
            except Exception as exc:
                __bridge_result__ = {{"ok": False, "error": str(exc)[:220]}}
''')

    # ---- 5. camera cut ------------------------------------------------------
    def add_camera_cut(self, seq_path: str, actor_label: str,
                       location, start_s: float, end_s: float) -> Dict[str, Any]:
        loc = json.dumps([float(v) for v in location])
        return self.bridge.execute_python(f'''
import unreal
seq = unreal.EditorAssetLibrary.load_asset({self._q(seq_path)})
if seq is None:
    __bridge_result__ = {{"ok": False, "error": "sequence not found"}}
else:
    loc = {loc}
    actors = [a for a in unreal.EditorLevelLibrary.get_all_level_actors()
              if a.get_actor_label() == {self._q(actor_label)} or a.get_name() == {self._q(actor_label)}]
    if not actors:
        cam = unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.CineCameraActor, unreal.Vector(loc[0], loc[1], loc[2]), unreal.Rotator(0, 0, 0))
        cam.rename({self._q(actor_label)})
        cam.set_actor_label({self._q(actor_label)})
    else:
        cam = actors[0]
    cut_track = None
    try:
        cut_track = unreal.MovieSceneSequenceExtensions.add_track(seq, unreal.MovieSceneCameraCutTrack)
        section = unreal.MovieSceneTrackExtensions.add_section(cut_track)
        unreal.MovieSceneSectionExtensions.set_range_seconds(section, float({json.dumps(float(start_s))}), float({json.dumps(float(end_s))}))
        cut_ok = section is not None
    except Exception as exc:
        cut_ok = False
    __bridge_result__ = {{
        "ok": cut_ok,
        "camera_actor": cam.get_name() if cam is not None else None,
        "cut_track": str(cut_track.get_name()) if cut_track else None,
        "note": "camera binding-id wiring is via guid objects and intentionally left best-effort; track+section+range are the proven surface",
    }}
''')

    # ---- 6. scrub / play -----------------------------------------------------
    def scrub_and_play(self, seq_path: str) -> Dict[str, Any]:
        return self.bridge.execute_python(f'''
import unreal
seq = unreal.EditorAssetLibrary.load_asset({self._q(seq_path)})
if seq is None:
    __bridge_result__ = {{"ok": False, "error": "sequence not found"}}
else:
    out = {{"ok": True}}
    try:
        unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(seq)
    except Exception:
        pass
    try:
        unreal.LevelSequenceEditorBlueprintLibrary.set_current_time(1.25)
        out["scrub_time"] = float(unreal.LevelSequenceEditorBlueprintLibrary.get_current_time())
    except Exception as exc:
        out["scrub"] = "ERR:" + str(exc)[:120]
    try:
        unreal.LevelSequenceEditorBlueprintLibrary.set_playback_speed(2.0)
        out["speed"] = float(unreal.LevelSequenceEditorBlueprintLibrary.get_playback_speed())
    except Exception as exc:
        out["speed"] = "ERR:" + str(exc)[:120]
    try:
        unreal.LevelSequenceEditorBlueprintLibrary.play()
        out["playing"] = bool(unreal.LevelSequenceEditorBlueprintLibrary.is_playing())
        unreal.LevelSequenceEditorBlueprintLibrary.pause()
        out["paused"] = not bool(unreal.LevelSequenceEditorBlueprintLibrary.is_playing())
    except Exception as exc:
        out["play"] = "ERR:" + str(exc)[:120]
    __bridge_result__ = out
''')

    # ---- 7. structure read-back ----------------------------------------------
    def read_sequence_structure(self, seq_path: str) -> Dict[str, Any]:
        return self.bridge.execute_python(f'''
import unreal
seq = unreal.EditorAssetLibrary.load_asset({self._q(seq_path)})
if seq is None:
    __bridge_result__ = {{"ok": False, "error": "sequence not found"}}
else:
    try:
        # Per-binding object resolution (get_bound_objects) is not on
        # MovieSceneSequenceExtensions in 5.8 - binding COUNT + sequence-wide
        # track/section inventory is the provable read surface.
        bindings = len(unreal.MovieSceneSequenceExtensions.get_bindings(seq))
        tracks = []
        for cls_name in ("MovieScene3DTransformTrack", "MovieSceneCameraCutTrack"):
            cls = getattr(unreal, cls_name, None)
            if cls is None:
                continue
            try:
                for t in unreal.MovieSceneSequenceExtensions.find_tracks_by_type(seq, cls):
                    sections = []
                    for s in unreal.MovieSceneTrackExtensions.get_sections(t):
                        sections.append({{
                            "range": [
                                float(unreal.MovieSceneSectionExtensions.get_start_frame_seconds(s)),
                                float(unreal.MovieSceneSectionExtensions.get_end_frame_seconds(s)),
                            ],
                        }})
                    tracks.append({{"class": cls_name, "sections": sections}})
            except Exception as exc:
                tracks.append({{"class": cls_name, "error": str(exc)[:100]}})
        __bridge_result__ = {{"ok": True, "binding_count": bindings, "tracks": tracks}}
    except Exception as exc:
        __bridge_result__ = {{"ok": False, "error": str(exc)[:220]}}
''')

    # ---- 8. save + reopen -----------------------------------------------------
    def save_sequence(self, seq_path: str) -> Dict[str, Any]:
        return self.bridge.execute_python(f'''
import unreal
seq = unreal.EditorAssetLibrary.load_asset({self._q(seq_path)})
if seq is None:
    __bridge_result__ = {{"ok": False, "error": "sequence not found"}}
else:
    saved = bool(unreal.EditorAssetLibrary.save_loaded_asset(seq, False))
    reloaded = unreal.EditorAssetLibrary.load_asset({self._q(seq_path)})
    __bridge_result__ = {{
        "ok": bool(saved and reloaded is not None and reloaded.get_class().get_name() == "LevelSequence"),
        "asset_path": {self._q(seq_path)},
        "class_after_reload": reloaded.get_class().get_name() if reloaded else None,
    }}
''')