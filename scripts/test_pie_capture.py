import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.unreal.unreal_bridge import UnrealBridge

bridge = UnrealBridge()

def inner(value):
    if isinstance(value, dict) and isinstance(value.get("result"), dict):
        return value["result"]
    return value if isinstance(value, dict) else {}

def show(label, ok, detail=""):
    status = "OK" if ok else "FAIL"
    print(f"{label}: {status}" + (f" | {detail}" if detail else ""))

# 1. Bridge
ping = bridge.ping()
ping_ok = bool(isinstance(ping, dict) and ping.get("ok"))
show("Unreal bridge", ping_ok)
if not ping_ok:
    print(json.dumps(ping, indent=2, default=str))
    sys.exit(1)

# 2. PIE status/start
status_raw = bridge.get_pie_status()
status = inner(status_raw)

if not status.get("is_playing"):
    start_raw = bridge.start_pie()
    show("PIE start request", bool(start_raw.get("ok") if isinstance(start_raw, dict) else False))

    ready = False
    for _ in range(20):
        time.sleep(0.25)
        status_raw = bridge.get_pie_status()
        status = inner(status_raw)
        if status.get("is_playing"):
            ready = True
            break
else:
    ready = True

show("PIE", ready, str(status.get("world_name")))

if not ready:
    print(json.dumps(status_raw, indent=2, default=str))
    sys.exit(2)

# 3. Native game viewport capture
capture_raw = bridge.capture_pie_viewport()
capture = inner(capture_raw)

capture_ok = (
    capture.get("ok") is True
    and capture.get("source_is_game_viewport") is True
    and int(capture.get("size") or 0) > 0
)

show(
    "Native GameViewport",
    capture.get("source_is_game_viewport") is True,
    str(capture.get("diagnostic") or capture.get("error") or "")
)

show(
    "Screenshot",
    capture_ok,
    f'{capture.get("size", 0)} bytes | {capture.get("path", "")}'
)

# 4. Stop PIE
stop_raw = bridge.stop_pie()
show("PIE stop", bool(stop_raw.get("ok") if isinstance(stop_raw, dict) else False))

print()
if capture_ok:
    print("PASS")
    sys.exit(0)

print("FAIL")
print(json.dumps(capture_raw, indent=2, default=str))

# Helpful stale/native detection
text = json.dumps(capture_raw, default=str)
if "HighResShot" in text or "Shot produced" in text:
    print("CAUSE: old Agent capture implementation is still being used.")
elif "source_is_game_viewport" not in capture:
    print("CAUSE: native/Agent capture version is stale or not loaded.")
elif not capture.get("source_is_game_viewport"):
    print("CAUSE: native plugin did not expose GameViewport; rebuild/restart Unreal.")
else:
    print("CAUSE: GameViewport was detected but PNG verification failed.")

sys.exit(3)
