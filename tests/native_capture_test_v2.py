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

@unreal.AutomationScheduler.add_latent_command
def ua_capture():
    task = unreal.AutomationLibrary.take_high_res_screenshot(
        1280,
        720,
        path,
        delay=0.1,
        force_game_view=True
    )

    if not task.is_valid_task():
        print("UA_CAPTURE_INVALID")
        return

    print("UA_CAPTURE_REQUESTED")

    while not task.is_task_done():
        yield

    print("UA_CAPTURE_DONE")

__bridge_result__ = {{
    "scheduled": True,
    "path": path
}}
"""

result = bridge.execute_python(code)

print(json.dumps(
    result,
    ensure_ascii=False,
    indent=2
))

deadline = time.time() + 60
last_size = -1
stable = 0

while time.time() < deadline:

    if os.path.isfile(path):

        size = os.path.getsize(path)

        if size > 1000:

            if size == last_size:
                stable += 1
            else:
                stable = 0

            last_size = size

            if stable >= 3:
                print()
                print("NATIVE_CAPTURE_OK")
                print(path)
                print("SIZE =", size)
                raise SystemExit(0)

    time.sleep(0.5)

print()
print("NATIVE_CAPTURE_FAILED")
raise SystemExit(2)