"""Minimal: load HQ, teleport editor camera, report full envelope."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.unreal.unreal_bridge import UnrealBridge  # noqa: E402

BRIDGE = UnrealBridge(host="127.0.0.1", port=6766, timeout=180)

out = BRIDGE.execute_python(r"""
import unreal
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
loaded = les.load_level("/Game/Maps/AividoHQ")
w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
try:
    unreal.EditorLevelLibrary.set_level_viewport_camera_info(
        unreal.Vector(0, -2600, 1100), unreal.Rotator(-18, 90, 0))
    cam_err = None
except Exception as e:
    cam_err = str(e)
loc = rot = None
try:
    loc, rot = unreal.EditorLevelLibrary.get_level_viewport_camera_info()
except Exception as e:
    cam_err = (cam_err or "") + " get:" + str(e)
__bridge_result__ = {"loaded": bool(loaded), "level": w.get_path_name(), "cam_err": cam_err,
                     "cam": [round(loc.x, 0), round(loc.y, 0), round(loc.z, 0)] if loc else None}
""")
print(json.dumps(out, indent=1, default=str)[:1200])
