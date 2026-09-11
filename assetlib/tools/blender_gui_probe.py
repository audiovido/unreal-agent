"""FREEBUFF ASSET P1: Blender GUI probe.

Runs inside a GUI-mode Blender (no --background) and proves the interactive
session is alive: bpy, active workspace, GPU module, then writes a marker file
and quits cleanly.

Usage: blender.exe --python blender_gui_probe.py -- <marker_json_path>
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def main() -> None:
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    marker_path = Path(args[0]) if args else Path.home() / "blender_gui_marker.json"

    import bpy
    import sys as _sys

    started = time.time()
    info = {
        "gui_alive": False,
        "version": bpy.app.version_string,
        "python": _sys.version.split()[0],
        "started_at": started,
        "error": None,
    }

    # A plain object add only works once a window/data context is ready; the
    # startup scene already exists in GUI mode, so we just read state that only
    # exists with a real UI session.
    try:
        workspace = bpy.context.workspace.name if bpy.context.workspace else None
        screen = bpy.context.screen.name if bpy.context.screen else None
        info["workspace"] = workspace
        info["screen"] = screen
        info["objects"] = [o.name for o in bpy.data.objects]
        try:
            import gpu  # only meaningful with a GL context

            info["gpu_module"] = True
        except Exception as exc:
            info["gpu_module"] = False
            info["gpu_error"] = str(exc)
        info["gui_alive"] = bool(workspace and screen)
    except Exception as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"

    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(json.dumps(info, indent=2, default=str), encoding="utf-8")

    def _quit() -> float | None:
        try:
            bpy.ops.wm.quit_blender()
        except Exception:
            pass
        return None

    # Give the host time to locate and screenshot the window.
    bpy.app.timers.register(_quit, first_interval=4.0)
    print("GUI_PROBE registered", flush=True)


if __name__ == "__main__":
    main()
