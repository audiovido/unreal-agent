"""Force-end stuck PIE via console Exit, then recover editor."""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.unreal.unreal_bridge import UnrealBridge  # noqa: E402

BRIDGE = UnrealBridge(host="127.0.0.1", port=6766, timeout=180)

cmd = BRIDGE.execute_python(r"""
import unreal
game = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
if game is None:
    __bridge_result__ = {"ok": True, "note": "no game world"}
else:
    unreal.SystemLibrary.execute_console_command(game, "Exit", None)
    __bridge_result__ = {"ok": True, "note": "Exit sent to " + game.get_path_name()}
""")
print("cmd:", json.dumps(cmd.get("result"), default=str)[:200], str(cmd.get("error"))[:200])
time.sleep(8)

st = BRIDGE.execute_python(r"""
import unreal
game = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
__bridge_result__ = {"game": game.get_path_name() if game else None,
                     "editor": world.get_path_name() if world else None}
""")
print("state:", json.dumps(st.get("result"), default=str)[:200])

rl = BRIDGE.execute_python(r"""
import unreal
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
loaded = les.load_level("/Game/Maps/AividoHQ")
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
__bridge_result__ = {"loaded": bool(loaded), "world": world.get_path_name() if world else None}
""")
print("reload:", json.dumps(rl.get("result"), default=str)[:200])
