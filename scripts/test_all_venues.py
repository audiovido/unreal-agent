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
    r"C:\Users\Shadow\Desktop\app\AudioVidoLivingCity\Saved\UnrealAgent\AllVenues"
)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

VENUES = [
    (0, "lumiere_cinema"),
    (1, "velvet_room"),
    (2, "the_forum"),
    (3, "common_ground"),
]


def inner(value):
    if isinstance(value, dict) and isinstance(value.get("result"), dict):
        return value["result"]
    return value if isinstance(value, dict) else {}


def fail(message, raw=None):
    print()
    print("FAIL:", message)

    if raw is not None:
        print(json.dumps(raw, indent=2, default=str))

    try:
        bridge.stop_pie()
    except Exception:
        pass

    sys.exit(1)


def run_controller_call(expression):
    return bridge.execute_python(f"""
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
        ok = bool({expression})
    except Exception:
        ok = False

__bridge_result__ = {{
    "ok": ok,
    "controller": pc.get_name() if pc else None
}}
""")


def capture_named(name):
    raw = bridge.capture_pie_viewport()
    result = inner(raw)

    if not (
        result.get("ok") is True
        and result.get("source_is_game_viewport") is True
        and int(result.get("size") or 0) > 0
    ):
        fail(f"{name}: GameViewport capture failed", raw)

    src = Path(result["path"])

    if not src.is_file():
        fail(f"{name}: screenshot source missing", raw)

    dst = OUTPUT_DIR / f"{name}.png"
    shutil.copy2(src, dst)

    if not dst.is_file() or dst.stat().st_size <= 0:
        fail(f"{name}: screenshot copy verification failed")

    print(
        f"{name}: CAPTURE OK | "
        f"{dst.stat().st_size} bytes | {dst}"
    )

    return dst


# ------------------------------------------------------------
# Bridge + PIE
# ------------------------------------------------------------

ping = bridge.ping()

if not isinstance(ping, dict) or not ping.get("ok"):
    fail("Unreal bridge unavailable", ping)

status = inner(bridge.get_pie_status())

if not status.get("is_playing"):
    start = bridge.start_pie()

ready = False

for _ in range(40):
    time.sleep(0.2)
    status = inner(bridge.get_pie_status())

    if status.get("is_playing"):
        ready = True
        break

if not ready:
    fail("PIE did not become ready")

print("PIE: OK |", status.get("world_name"))

time.sleep(0.8)

try:
    # --------------------------------------------------------
    # Welcome -> City
    # --------------------------------------------------------

    dismiss_raw = run_controller_call(
        "pc.automation_dismiss_welcome()"
    )

    if inner(dismiss_raw).get("ok") is not True:
        fail("AutomationDismissWelcome failed", dismiss_raw)

    print("WELCOME: DISMISSED")
    time.sleep(0.4)

    # --------------------------------------------------------
    # All venues
    # --------------------------------------------------------

    for index, slug in VENUES:
        print()
        print(f"VENUE {index}: {slug}")

        select_raw = run_controller_call(
            f"pc.automation_select_venue({index})"
        )

        if inner(select_raw).get("ok") is not True:
            fail(
                f"Venue {index} selection failed",
                select_raw
            )

        print("  SELECT: OK")

        # Let smooth camera interpolation settle.
        time.sleep(1.15)

        capture_named(
            f"{index + 1:02d}_{slug}"
        )

        clear_raw = run_controller_call(
            "pc.automation_clear_venue()"
        )

        if inner(clear_raw).get("ok") is not True:
            fail(
                f"Venue {index} clear/reset failed",
                clear_raw
            )

        print("  CLEAR + CAMERA RESET: OK")

        # Let ResetView interpolation settle before next venue.
        time.sleep(0.85)

finally:
    stop = bridge.stop_pie()

    stop_ok = (
        isinstance(stop, dict)
        and stop.get("ok") is True
    )

    print()
    print("PIE stop:", "OK" if stop_ok else "FAIL")


expected = [
    OUTPUT_DIR / f"{index + 1:02d}_{slug}.png"
    for index, slug in VENUES
]

for path in expected:
    if not path.is_file() or path.stat().st_size <= 0:
        fail(f"Expected screenshot missing: {path}")


print()
print("========================================")
print("PASS ? ALL 4 VENUES")
print("========================================")

for index, slug in VENUES:
    print(
        f"{index}: {slug} | "
        f"SELECT OK | CAPTURE OK | CLEAR OK"
    )

print()
print("Screenshots:")

for path in expected:
    print(path)
