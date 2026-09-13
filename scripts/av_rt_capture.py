"""Bridge-side: inspect PP exposure + capture via proven VCam RT route."""
import os
import time

import unreal

OUT_DIR = "/Users/admin/Projects/AividoAgentHost/Saved/UnrealAgent"
os.makedirs(OUT_DIR, exist_ok=True)
report = {}


def find_actor(label):
    for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors():
        if a.get_actor_label() == label:
            return a
    return None


# 1) PostProcess exposure state
pp = find_actor("AIVIDO_PostProcess")
if pp:
    s = pp.get_editor_property("settings")
    try:
        report["pp"] = {
            "unbound": pp.get_editor_property("unbound"),
            "method": str(s.auto_exposure_method),
            "bias": s.auto_exposure_bias,
            "min_ev": s.get_editor_property("auto_exposure_min_brightness"),
            "max_ev": s.get_editor_property("auto_exposure_max_brightness"),
        }
    except Exception as e:
        report["pp_error"] = str(e)

# 2) VCam RT capture (proven non-black route)
vcam = find_actor("AIVIDO_VCam")
if vcam is None:
    report["vcam"] = "MISSING"
else:
    comp = vcam.get_component_by_class(unreal.SceneCaptureComponent2D)
    world = unreal.EditorLevelLibrary.get_editor_world()
    rt = comp.texture_target
    if rt is None:
        rt = unreal.RenderingLibrary.create_render_target2d(
            world, 1280, 720, unreal.TextureRenderTargetFormat.RTF_RGBA8)
        comp.texture_target = rt
    comp.capture_source = unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR
    path = os.path.join(OUT_DIR, "overnight_rt.png")
    if os.path.isfile(path):
        os.remove(path)
    comp.capture_scene()
    time.sleep(0.8)
    unreal.RenderingLibrary.export_render_target(world, rt, OUT_DIR, "overnight_rt.png")
    time.sleep(0.4)
    report["rt"] = {"path": path,
                    "size": os.path.getsize(path) if os.path.isfile(path) else 0}

__bridge_result__ = report
