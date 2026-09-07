"""cinematic_live_probe.py — read-only live Unreal probe for the V2 demo.

Connects to the live Unreal bridge (127.0.0.1:6766) and reports what the
cinematic pipeline can actually use: project identity, current level, actor
class census, MRQ subsystem exposure, Sequencer/CineCamera surface, and the
available /Game maps. NO mutations.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def probe() -> dict:
    from tools.unreal.unreal_bridge import UnrealBridge
    bridge = UnrealBridge(timeout=20)

    out: dict = {}
    out["ping"] = bridge.ping()
    out["identity"] = bridge.get_project_identity()
    out["level"] = bridge.get_current_level()
    mrq = bridge.execute_python(r'''
import unreal
found = {}
for name in ("MovieRenderQueueSubsystem", "MoviePipelineEditorExecutor",
             "MoviePipelineExecutorJob", "MoviePipelinePrimaryConfig",
             "CineCameraActor", "LevelSequenceEditorSubsystem",
             "LevelSequenceEditorBlueprintLibrary"):
    found[name] = hasattr(unreal, name)
__bridge_result__ = found
''')
    out["unreal_surface"] = mrq.get("result") if isinstance(
        mrq, dict) and isinstance(mrq.get("result"), dict) else mrq
    census = bridge.execute_python(r'''
import unreal
from collections import Counter
counts = Counter()
actors = unreal.EditorLevelLibrary.get_all_level_actors()
labels = []
for a in actors:
    cls = a.get_class().get_name()
    counts[cls] += 1
    label = (a.get_actor_label() or "").lower()
    if any(k in label for k in ("hq", "char", "worker", "agent", "ava",
                                "suv", "truck", "hero")):
        loc = a.get_actor_location()
        labels.append({"label": a.get_actor_label(), "class": cls,
                       "loc": [round(loc.x, 1), round(loc.y, 1), round(loc.z, 1)]})
__bridge_result__ = {"total": len(actors),
                     "by_class": [{"class": c, "count": n}
                                  for c, n in counts.most_common(25)],
                     "hero_candidates": labels[:40]}
''')
    out["census"] = census.get("result") if isinstance(
        census, dict) and isinstance(census.get("result"), dict) else census
    maps = bridge.execute_python(r'''
import unreal
rows = []
for a in sorted(unreal.EditorAssetLibrary.list_assets("/Game", recursive=True)):
    obj = unreal.EditorAssetLibrary.load_asset(a)
    if obj is not None and obj.get_class().get_name() == "World":
        rows.append(str(a))
__bridge_result__ = rows
''')
    out["maps"] = maps.get("result") if isinstance(
        maps, dict) and isinstance(maps.get("result"), list) else maps
    return out


if __name__ == "__main__":
    result = probe()
    print(json.dumps(result, indent=2, default=str))
