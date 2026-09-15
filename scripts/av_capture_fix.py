"""Bridge-side: fix over-dense fog + capture via window-independent VCam RT."""
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


# 1) Fog: keep atmospheric depth but restore readability (0.06 -> 0.012)
fog = find_actor("AIVIDO_Fog")
fc = fog.get_component_by_class(unreal.ExponentialHeightFogComponent) if fog else None
if fc:
    fc.set_editor_property("fog_density", 0.012)
    try:
        fc.set_editor_property("fog_inscattering_luminance",
                               unreal.LinearColor(0.12, 0.10, 0.085, 1.0))
    except Exception:
        pass
    report["fog_density_set"] = 0.012

# 2) VCam RT capture with a fresh LDR-compatible render target
vcam = find_actor("AIVIDO_VCam")
if vcam is None:
    report["vcam"] = "MISSING"
else:
    comp = vcam.get_component_by_class(unreal.SceneCaptureComponent2D)
    world = unreal.EditorLevelLibrary.get_editor_world()
    rt = unreal.RenderingLibrary.create_render_target2d(
        world, 1600, 900, unreal.TextureRenderTargetFormat.RTF_RGBA8)
    comp.texture_target = rt
    comp.capture_source = unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR
    time.sleep(0.5)
    path = os.path.join(OUT_DIR, "overnight_rt2.png")
    if os.path.isfile(path):
        os.remove(path)
    comp.capture_scene()
    time.sleep(1.2)
    unreal.RenderingLibrary.export_render_target(world, rt, OUT_DIR, "overnight_rt2.png")
    time.sleep(0.4)
    report["rt_capture"] = {
        "path": path,
        "size": os.path.getsize(path) if os.path.isfile(path) else 0,
    }

# 3) Native viewport capture (expected black while window hidden; informational)
p2 = os.path.join(OUT_DIR, "overnight_latest.png")
if os.path.isfile(p2):
    os.remove(p2)
diag = str(unreal.UnrealAgentBlueprintLibrary.capture_active_viewport_detailed(p2))
report["native"] = {"diag": diag[:100],
                    "size": os.path.getsize(p2) if os.path.isfile(p2) else 0}

__bridge_result__ = report
