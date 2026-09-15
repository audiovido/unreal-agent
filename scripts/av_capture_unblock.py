"""Bridge-side: unblock black captures (background throttle) + HRSS camera route."""
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


# 1) Disable background CPU throttling (editor pref + CVar mirrors)
try:
    perf = unreal.get_default_object(unreal.EditorPerformanceSettings)
    before = perf.get_editor_property("throttle_cpu_when_not_foreground")
    perf.set_editor_property("throttle_cpu_when_not_foreground", False)
    report["throttle"] = {"before": before, "after": False}
except Exception as e:
    report["throttle_err"] = str(e)[:160]
unreal.SystemLibrary.execute_console_command(
    unreal.EditorLevelLibrary.get_editor_world(),
    "r.Editor.ThrottleCPUWhenNotForeground 0")
report["cvar_set"] = "r.Editor.ThrottleCPUWhenNotForeground 0"
time.sleep(2.0)

# 2) Native viewport capture retry
p = os.path.join(OUT_DIR, "unblock_native.png")
if os.path.isfile(p):
    os.remove(p)
diag = str(unreal.UnrealAgentBlueprintLibrary.capture_active_viewport_detailed(p))
report["native_after_throttle_off"] = {"diag": diag[:110],
                                       "size": os.path.getsize(p) if os.path.isfile(p) else 0}

# 3) High-res screenshot bound to HeroCamera (renders at its own resolution)
cam = find_actor("AIVIDO_HeroCamera")
if cam is None:
    report["hrss"] = "HERO_CAMERA_MISSING"
else:
    hp = os.path.join(OUT_DIR, "unblock_hrss.png")
    if os.path.isfile(hp):
        os.remove(hp)
    try:
        unreal.AutomationLibrary.take_high_res_screenshot(
            1920, 1080, hp, cam, False, False, force_game_view=False)
        deadline = time.time() + 25
        while time.time() < deadline and not os.path.isfile(hp):
            time.sleep(0.5)
        time.sleep(1.5)
        report["hrss"] = {"path": hp,
                          "size": os.path.getsize(hp) if os.path.isfile(hp) else 0}
    except Exception as e:
        report["hrss_err"] = str(e)[:200]

__bridge_result__ = report
