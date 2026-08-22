import json
import os
import time

from tools.unreal.unreal_bridge import UnrealBridge

bridge = UnrealBridge(timeout=30)
last = None

for attempt in range(1, 7):
    last = bridge.capture_unreal_viewport()

    print(f"ATTEMPT {attempt}")
    print(json.dumps(last, ensure_ascii=False, indent=2))

    info = (last or {}).get("result") or {}

    if (
        isinstance(last, dict)
        and last.get("ok")
        and info.get("ok")
        and info.get("size", 0) > 1000
        and os.path.isfile(info.get("path", ""))
    ):
        print()
        print("NATIVE_CAPTURE_V5_1_PASS")
        print(info.get("path"))
        raise SystemExit(0)

    time.sleep(2)

print()
print("NATIVE_CAPTURE_V5_1_FAILED")
print(json.dumps(last, ensure_ascii=False, indent=2))
raise SystemExit(2)
