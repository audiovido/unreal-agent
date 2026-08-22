import os
import time
import json

from tools.unreal.unreal_bridge import UnrealBridge

path = os.path.join(
    os.environ["LOCALAPPDATA"],
    "UnrealAgent",
    "captures",
    "native_viewport_test.png",
)

os.makedirs(os.path.dirname(path), exist_ok=True)

try:
    os.remove(path)
except FileNotFoundError:
    pass

bridge = UnrealBridge(timeout=30)

code = f"""
import unreal

path = {path!r}

task = unreal.AutomationLibrary.take_high_res_screenshot(
    1280,
    720,
    path
)

__bridge_result__ = {{
    "requested": True,
    "task_valid": task.is_valid_task(),
    "path": path,
    "saved_dir": unreal.Paths.project_saved_dir()
}}
"""

result = bridge.execute_python(code)

print(json.dumps(
    result,
    ensure_ascii=False,
    indent=2
))

deadline = time.time() + 40
previous_size = -1
stable_count = 0

while time.time() < deadline:

    if os.path.isfile(path):

        size = os.path.getsize(path)

        if size > 1000:

            if size == previous_size:
                stable_count += 1
            else:
                stable_count = 0

            previous_size = size

            if stable_count >= 2:
                print()
                print("NATIVE_CAPTURE_OK")
                print(path)
                print("SIZE =", size)
                raise SystemExit(0)

    time.sleep(0.5)

print()
print("NATIVE_CAPTURE_FAILED")
raise SystemExit(2)