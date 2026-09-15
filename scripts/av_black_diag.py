"""Bridge-side: diagnose black render — fog probe, fog-off test capture."""
import os
import time

import unreal

OUT_DIR = "/Users/admin/Projects/AividoAgentHost/Saved/UnrealAgent"
report = {}


def find_actor(label):
    for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors():
        if a.get_actor_label() == label:
            return a
    return None


def native_capture(name):
    path = os.path.join(OUT_DIR, name)
    if os.path.isfile(path):
        os.remove(path)
    diag = str(unreal.UnrealAgentBlueprintLibrary.capture_active_viewport_detailed(path))
    deadline = time.time() + 10
    while time.time() < deadline and (not os.path.isfile(path) or os.path.getsize(path) == 0):
        time.sleep(0.3)
    time.sleep(1.2)
    return {"path": path, "size": os.path.getsize(path) if os.path.isfile(path) else 0,
            "diag": diag[:120]}


# 1) Fog state
fog = find_actor("AIVIDO_Fog")
fc = fog.get_component_by_class(unreal.ExponentialHeightFogComponent) if fog else None
if fc:
    try:
        report["fog_before"] = {
            "density": fc.get_editor_property("fog_density"),
            "inscatter": str(fc.get_editor_property("fog_inscattering_luminance")),
            "height_falloff": fc.get_editor_property("fog_height_falloff"),
        }
    except Exception as e:
        report["fog_read_err"] = str(e)

# 2) Fog-off capture (restore right after)
if fc:
    fc.set_editor_property("fog_density", 0.0)
    time.sleep(1.0)
    report["capture_fog_off"] = native_capture("diag_fogoff.png")
    fc.set_editor_property("fog_density", report["fog_before"]["density"])
    time.sleep(1.0)
    report["capture_fog_restored"] = native_capture("diag_fogon.png")

# 3) Plain settled capture, two samples
report["capture_settle"] = native_capture("diag_settle.png")

__bridge_result__ = report
