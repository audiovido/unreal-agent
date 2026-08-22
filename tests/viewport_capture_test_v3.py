import os
import time
import json

from tools.unreal.unreal_bridge import UnrealBridge

bridge = UnrealBridge(timeout=30)

code = r"""
import os
import unreal

saved_dir = unreal.Paths.convert_relative_path_to_full(
    unreal.Paths.project_saved_dir()
)

out_dir = os.path.join(
    saved_dir,
    "Screenshots",
    "Windows"
)

os.makedirs(out_dir, exist_ok=True)

base_name = "UA_Viewport_Test"

requested_path = os.path.join(
    out_dir,
    base_name + ".png"
)

done_path = os.path.join(
    out_dir,
    base_name + ".done"
)

error_path = os.path.join(
    out_dir,
    base_name + ".error.txt"
)

for p in (
    requested_path,
    done_path,
    error_path
):
    try:
        os.remove(p)
    except Exception:
        pass

state = {
    "phase": "start",
    "task": None,
    "handle": None,
}

def ua_screenshot_tick(delta_seconds):

    try:

        if state["phase"] == "start":

            task = unreal.AutomationLibrary.take_high_res_screenshot(
                1280,
                720,
                requested_path,
                delay=0.0,
                force_game_view=True
            )

            if not task.is_valid_task():

                with open(
                    error_path,
                    "w",
                    encoding="utf-8"
                ) as f:
                    f.write(
                        "Screenshot task was invalid."
                    )

                unreal.unregister_slate_post_tick_callback(
                    state["handle"]
                )

                return

            state["task"] = task
            state["phase"] = "wait"

            return

        if state["phase"] == "wait":

            task = state["task"]

            if (
                task is not None
                and task.is_task_done()
            ):

                with open(
                    done_path,
                    "w",
                    encoding="utf-8"
                ) as f:
                    f.write("done")

                unreal.unregister_slate_post_tick_callback(
                    state["handle"]
                )

    except Exception as exc:

        try:
            with open(
                error_path,
                "w",
                encoding="utf-8"
            ) as f:
                f.write(repr(exc))
        except Exception:
            pass

        try:
            unreal.unregister_slate_post_tick_callback(
                state["handle"]
            )
        except Exception:
            pass

state["handle"] = unreal.register_slate_post_tick_callback(
    ua_screenshot_tick
)

__bridge_result__ = {
    "scheduled": True,
    "requested_path": requested_path,
    "done_path": done_path,
    "error_path": error_path,
    "out_dir": out_dir,
}
"""

result = bridge.execute_python(code)

print(
    json.dumps(
        result,
        ensure_ascii=False,
        indent=2
    )
)

if not result.get("ok"):
    raise SystemExit(2)

info = result.get("result") or {}

out_dir = info.get("out_dir")
done_path = info.get("done_path")
error_path = info.get("error_path")

start = time.time()
deadline = start + 60

candidate = None

while time.time() < deadline:

    if (
        error_path
        and os.path.isfile(error_path)
    ):
        print()
        print("VIEWPORT_CAPTURE_FAILED")

        with open(
            error_path,
            "r",
            encoding="utf-8"
        ) as f:
            print(f.read())

        raise SystemExit(2)

    if out_dir and os.path.isdir(out_dir):

        pngs = []

        for name in os.listdir(out_dir):

            if not name.lower().endswith(".png"):
                continue

            path = os.path.join(
                out_dir,
                name
            )

            try:
                mtime = os.path.getmtime(path)
                size = os.path.getsize(path)
            except OSError:
                continue

            if (
                mtime >= start - 2
                and size > 1000
            ):
                pngs.append(
                    (
                        mtime,
                        size,
                        path
                    )
                )

        if pngs:
            pngs.sort(reverse=True)
            candidate = pngs[0][2]

    if (
        candidate
        and done_path
        and os.path.isfile(done_path)
    ):

        print()
        print("VIEWPORT_CAPTURE_OK")
        print(candidate)
        print(
            "SIZE =",
            os.path.getsize(candidate)
        )

        raise SystemExit(0)

    time.sleep(0.5)

if candidate:

    print()
    print("VIEWPORT_CAPTURE_OK")
    print(candidate)

    raise SystemExit(0)

print()
print("VIEWPORT_CAPTURE_FAILED")

raise SystemExit(2)