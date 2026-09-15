"""SMALLEST REVERSIBLE FIX: the live level viewport sits OUTSIDE the room at the
HeroCamera pose, staring into the unlit exterior of AIVIDO_FrontWall (37cm away).
Move the viewport to an interior wide vantage computed from room bounds, then
capture frame B for the liveness proof.

BEFORE pose (restore path): loc=(-950,-420,235) rot rpY=(-8,0,27)
AFTER  pose (interior wide): loc=(-820,-350,270) rot rpY=(0,-10,0)

The viewport pose is transient editor UI state, not stored in the map asset:
reverting is one setter call. Nothing else is modified.

Targets the viewport must see (verified in /tmp/av_probe.json):
  Heidi (-620,-460)  W02 (-480,-290)  W03 (490,-300)  W01 (490,300)
  dais core (0,0,150)  UA station (560,-370)  AU station (560,370)
"""
import os

import unreal

saved_dir = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_saved_dir())
out_dir = os.path.join(saved_dir, "UnrealAgent")
os.makedirs(out_dir, exist_ok=True)
cap_b = os.path.join(out_dir, "liveness_B.png")
if os.path.isfile(cap_b):
    os.remove(cap_b)

ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)

NEW_LOC = unreal.Vector(-820.0, -350.0, 270.0)
NEW_ROT = unreal.Rotator(roll=0.0, pitch=-10.0, yaw=0.0)  # explicit kwargs: this build's
# positional Rotator order is (roll, pitch, yaw); kwargs make it unambiguous.

ues.set_level_viewport_camera_info(NEW_LOC, NEW_ROT)

diag = str(unreal.UnrealAgentBlueprintLibrary.capture_active_viewport_detailed(cap_b))
size = os.path.getsize(cap_b) if os.path.isfile(cap_b) else 0

# read back what the viewport actually reports now
got_loc, got_rot = ues.get_level_viewport_camera_info()
__bridge_result__ = {
    "moved_to": {"loc": [round(got_loc.x, 1), round(got_loc.y, 1), round(got_loc.z, 1)],
                 "rot_rpY": [round(got_rot.roll, 1), round(got_rot.pitch, 1), round(got_rot.yaw, 1)]},
    "capture_B": {"path": cap_b, "size": size, "diag": diag},
    "restore_path": {"loc": [-950.0, -420.0, 235.0], "rot_rpY": [-8.0, 0.0, 27.0]},
}
