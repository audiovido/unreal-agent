"""Quick host-side probe of the live Unreal editor (bridge 6766): current
level, actor count, cast presence, MRQ subsystem exposure. Read-only.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.unreal.unreal_bridge import UnrealBridge

code = r'''
import unreal
import json
ed = unreal.EditorActorSubsystem()
actors = ed.get_all_level_actors()
cast = [a.get_actor_label() for a in actors
        if (a.get_actor_label() or "").startswith("AVIDO_Human_")]
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
cls = ["MoviePipelineQueueSubsystem", "MovieRenderQueueSubsystem",
       "MoviePipelinePIEExecutor", "MoviePipelineInProcessExecutor",
       "MoviePipelineExecutorJob", "MoviePipelinePrimaryConfig", "MoviePipeline"]
present = [c for c in cls if hasattr(unreal, c)]
out = {
    "ok": True,
    "level": world.get_name() if world else None,
    "level_path": world.get_path_name() if world else None,
    "actor_count": len(actors),
    "cast_count": len(cast),
    "cast": sorted(cast)[:12],
    "mrq_classes_present": present,
}
__bridge_result__ = out
'''

if __name__ == "__main__":
    bridge = UnrealBridge(timeout=60)
    res = bridge.execute_python(code)
    print("RAW:", res)