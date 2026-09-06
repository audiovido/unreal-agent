"""Final capture attempt: enforce fresh mtime."""
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.unreal.unreal_bridge import UnrealBridge  # noqa: E402

BRIDGE = UnrealBridge(host="127.0.0.1", port=6766, timeout=180)
PROOF = ROOT / "assetlib" / "reports" / "worker5_w3_integrated_hq.png"
CAP_FILE = ROOT / "assetlib" / "tests" / "ue" / "ASSET_Showcase2" / "Saved" / "UnrealAgent" / "viewport_latest.png"

a = BRIDGE.execute_python(r"""
import unreal
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
les.load_level("/Game/Maps/AividoHQ")
unreal.EditorLevelLibrary.set_level_viewport_camera_info(
    unreal.Vector(150, -1400, 520), unreal.Rotator(-16, 90, 0))
time.sleep(1.0)
__bridge_result__ = {"ok": True}
""")
print("a:", json.dumps(a.get("result"), default=str)[:100])

t0 = time.time()
if CAP_FILE.exists():
    CAP_FILE.unlink()
cap = BRIDGE.capture_unreal_viewport()
print("cap:", json.dumps(cap.get("result"), default=str)[:120])

fresh = False
deadline = t0 + 45
while time.time() < deadline:
    if CAP_FILE.is_file() and CAP_FILE.stat().st_mtime > t0 and CAP_FILE.stat().st_size > 0:
        time.sleep(2)
        fresh = True
        break
    time.sleep(2)
if fresh:
    shutil.copyfile(CAP_FILE, PROOF)
    print("FRESH proof:", PROOF.stat().st_size, "bytes")
else:
    print("NO FRESH CAPTURE")
