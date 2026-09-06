"""Worker 4 UI proof via PIE pawn teleport (fresh capture path)."""
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.unreal.unreal_bridge import UnrealBridge  # noqa: E402

BRIDGE = UnrealBridge(host="127.0.0.1", port=6766, timeout=180)
PROOF = ROOT / "assetlib" / "reports" / "worker4_ui_hq.png"
CAP_DIR = ROOT / "assetlib" / "tests" / "ue" / "ASSET_Showcase2" / "Saved" / "UnrealAgent"

BRIDGE.execute_python(r"""
import unreal
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
les.load_level("/Game/Maps/AividoHQ")
__bridge_result__ = {"ok": True}
""")
time.sleep(4)
BRIDGE.start_pie()
time.sleep(7)

tele = BRIDGE.execute_python(r"""
import unreal
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
if world is None:
    __bridge_result__ = {"ok": False, "err": "no pie world"}
else:
    pc = unreal.GameplayStatics.get_player_controller(world, 0)
    pawn = pc.get_pawn() if pc else None
    if pawn is None:
        __bridge_result__ = {"ok": False, "err": "no pawn"}
    else:
        pawn.set_actor_location(unreal.Vector(0, -900, 400), False, False)
        pc.set_control_rotation(unreal.Rotator(-4, 180, 0))
        __bridge_result__ = {"ok": True, "pawn": pawn.get_name()}
""")
print("tele:", json.dumps(tele.get("result"), default=str)[:150])
time.sleep(4)

cap = BRIDGE.capture_pie_viewport()
print("cap:", json.dumps(cap.get("result"), default=str)[:160])
BRIDGE.stop_pie()
time.sleep(3)

src = CAP_DIR / "pie_viewport_latest.png"
if src.is_file() and src.stat().st_mtime > time.time() - 180:
    shutil.copyfile(src, PROOF)
    print("proof:", PROOF.stat().st_size, "bytes")
else:
    print("no fresh pie file")

BRIDGE.execute_python('les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem); les.load_level("/Game/Maps/AividoHQ"); __bridge_result__ = {"ok": True}')
print("restored")
