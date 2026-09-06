"""Final visual proof attempt: PIE capture of staging map."""
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.unreal.unreal_bridge import UnrealBridge  # noqa: E402

BRIDGE = UnrealBridge(host="127.0.0.1", port=6766, timeout=180)
PROOF_PNG = ROOT / "assetlib" / "reports" / "worker3_props_stage.png"
CAP_DIR = ROOT.parent / "Unreal-Agent" / "assetlib" / "tests" / "ue" / "ASSET_Showcase2" / "Saved" / "UnrealAgent"

load = BRIDGE.execute_python(r"""
import unreal
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
les.load_level("/Game/Maps/AividoHQ_PropsStage")
unreal.EditorLevelLibrary.set_level_viewport_camera_info(
    unreal.Vector(150, -1400, 520), unreal.Rotator(pitch=-18, yaw=90, roll=0))
w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
__bridge_result__ = {"level": w.get_path_name()}
""")
print("load:", load.get("result"))

pie = BRIDGE.start_pie()
print("pie start:", json.dumps(pie.get("result"), default=str)[:150])
time.sleep(6)

cap = BRIDGE.capture_pie_viewport()
print("pie capture:", json.dumps(cap.get("result"), default=str)[:200])

stop = BRIDGE.stop_pie()
print("pie stop:", json.dumps(stop.get("result"), default=str)[:120])

pie_file = None
for p in CAP_DIR.glob("*.png"):
    if p.stat().st_mtime > time.time() - 120:
        if pie_file is None or p.stat().st_mtime > pie_file.stat().st_mtime:
            pie_file = p
if pie_file:
    shutil.copyfile(pie_file, PROOF_PNG)
    print("proof:", pie_file.name, PROOF_PNG.stat().st_size, "bytes")
else:
    print("no fresh pie capture file")

r = BRIDGE.execute_python('les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem); les.load_level("/Game/Maps/AividoHQ"); __bridge_result__ = {"ok": True}')
print("restored:", r.get("ok"))
