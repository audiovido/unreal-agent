"""LIVENESS PROOF (task 4 of the foreground-capture mission).

Sequence on the live (foregrounded) editor:
  A  capture at hero pose
  -> CoreGlow intensity 2000 -> 200 (obvious, reversible)
  -> sleep ~2.5s for a real redraw
  B  capture (must differ from A)
  -> restore CoreGlow to 2000
  -> sleep ~2.5s
  C  capture (framing must match A; CoreGlow restored)

All three PNGs land in Saved/UnrealAgent/. Metrics are computed by the caller.
CoreGlow's original intensity is read at runtime and restored exactly.
"""
import os
import time

import unreal

saved_dir = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_saved_dir())
out_dir = os.path.join(saved_dir, "UnrealAgent")
os.makedirs(out_dir, exist_ok=True)
paths = {k: os.path.join(out_dir, f"live_{k}.png") for k in ("A", "B", "C")}
for p in paths.values():
    if os.path.isfile(p):
        os.remove(p)

ews = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
core = None
for a in ews.get_all_level_actors():
    if a.get_actor_label() == "AIVIDO_CoreGlow":
        core = a
        break
pc = core.get_component_by_class(unreal.PointLightComponent)
orig = float(pc.get_editor_property("intensity"))


def cap(tag):
    d = str(unreal.UnrealAgentBlueprintLibrary.capture_active_viewport_detailed(paths[tag]))
    return {"path": paths[tag], "size": os.path.getsize(paths[tag]) if os.path.isfile(paths[tag]) else 0,
            "diag": d}


res = {"core_orig": orig}
res["A"] = cap("A")

pc.set_editor_property("intensity", 200.0)   # obvious temporary change
time.sleep(2.5)                           # let the foregrounded editor redraw
res["B"] = cap("B")

pc.set_editor_property("intensity", orig)  # restore exactly
time.sleep(2.5)
res["C"] = cap("C")

__bridge_result__ = res
