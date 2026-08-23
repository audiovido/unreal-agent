import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.unreal.unreal_bridge import UnrealBridge

bridge = UnrealBridge()

OUTPUT_DIR = Path(
    r"C:\Users\Shadow\Desktop\app\AudioVidoLivingCity\Saved\UnrealAgent\UIStates"
)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def inner(value):
    if isinstance(value, dict) and isinstance(value.get("result"), dict):
        return value["result"]
    return value if isinstance(value, dict) else {}


def fail(message, raw=None):
    print("FAIL:", message)
    if raw is not None:
        print(json.dumps(raw, indent=2, default=str))
    try:
        bridge.stop_pie()
    except Exception:
        pass
    sys.exit(1)


def capture_named(name):
    raw = bridge.capture_pie_viewport()
    result = inner(raw)

    if not (
        result.get("ok") is True
        and result.get("source_is_game_viewport") is True
        and int(result.get("size") or 0) > 0
    ):
        fail(f"{name} capture failed", raw)

    src = Path(result["path"])
    if not src.is_file():
        fail(f"{name} screenshot file missing", raw)

    dst = OUTPUT_DIR / f"{name}.png"
    shutil.copy2(src, dst)

    if not dst.is_file() or dst.stat().st_size <= 0:
        fail(f"{name} copied screenshot verification failed")

    print(f"{name}: OK | {dst} | {dst.stat().st_size} bytes")
    return dst


# ------------------------------------------------------------
# Start PIE
# ------------------------------------------------------------

ping = bridge.ping()
if not isinstance(ping, dict) or not ping.get("ok"):
    fail("Unreal bridge unavailable", ping)

status_raw = bridge.get_pie_status()
status = inner(status_raw)

if not status.get("is_playing"):
    bridge.start_pie()

ready = False

for _ in range(30):
    time.sleep(0.2)
    status = inner(bridge.get_pie_status())

    if status.get("is_playing"):
        ready = True
        break

if not ready:
    fail("PIE did not become ready")

print("PIE: OK |", status.get("world_name"))

# Give HUD/city one moment to initialize.
time.sleep(0.6)

try:
    # --------------------------------------------------------
    # 1. Welcome
    # --------------------------------------------------------
    capture_named("01_welcome")

    # --------------------------------------------------------
    # 2. Main HUD
    # --------------------------------------------------------
    dismiss_raw = bridge.execute_python(r"""
editor_subsystem = unreal.get_editor_subsystem(
    unreal.UnrealEditorSubsystem
)
game_world = editor_subsystem.get_game_world()

pc = unreal.GameplayStatics.get_player_controller(
    game_world,
    0
) if game_world else None

ok = False

if pc is not None:
    try:
        ok = bool(pc.automation_dismiss_welcome())
    except Exception:
        ok = False

__bridge_result__ = {
    "ok": ok,
    "controller": pc.get_name() if pc else None
}
""")

    dismiss = inner(dismiss_raw)

    if dismiss.get("ok") is not True:
        fail(
            "AutomationDismissWelcome failed. "
            "Project probably needs rebuild/restart.",
            dismiss_raw
        )

    time.sleep(0.35)
    capture_named("02_main_hud")

    # --------------------------------------------------------
    # 3. Venue Detail
    # --------------------------------------------------------
    venue_raw = bridge.execute_python(r"""
editor_subsystem = unreal.get_editor_subsystem(
    unreal.UnrealEditorSubsystem
)
game_world = editor_subsystem.get_game_world()

pc = unreal.GameplayStatics.get_player_controller(
    game_world,
    0
) if game_world else None

ok = False

if pc is not None:
    try:
        ok = bool(pc.automation_select_venue(0))
    except Exception:
        ok = False

__bridge_result__ = {
    "ok": ok,
    "venue_index": 0,
    "controller": pc.get_name() if pc else None
}
""")

    venue = inner(venue_raw)

    if venue.get("ok") is not True:
        fail(
            "AutomationSelectVenue failed. "
            "Project probably needs rebuild/restart.",
            venue_raw
        )

    time.sleep(0.6)
    capture_named("03_venue_detail")

finally:
    stop = bridge.stop_pie()
    print("PIE stop:", "OK" if isinstance(stop, dict) and stop.get("ok") else "FAIL")

print()
print("PASS")
print("UI screenshots:")
print(OUTPUT_DIR / "01_welcome.png")
print(OUTPUT_DIR / "02_main_hud.png")
print(OUTPUT_DIR / "03_venue_detail.png")
