"""FREEBUFF ASSET: run editor-side Python inside a disposable UE project.

Launches UnrealEditor with -ExecutePythonScript, waits for a completion marker
JSON the script writes, then lets the editor exit by itself (the editor Python
calls os._exit after saving). Never kills pre-existing editors.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ASSETLIB = TOOLS.parent
if str(ASSETLIB.parent) not in sys.path:
    sys.path.insert(0, str(ASSETLIB.parent))
from assetlib.tools.env import discover_unreal  # noqa: E402

UNREAL = discover_unreal()


def run_ue_python(
    uproject_path: str | Path,
    script_path: str | Path,
    marker_path: str | Path,
    *,
    use_cmd: bool = False,
    timeout: int = 900,
    extra_args: list[str] | None = None,
    env_extra: dict | None = None,
) -> dict:
    """Run an editor Python script on a disposable project.

    The script must write a JSON marker file at marker_path and then exit the
    process itself (e.g. os._exit) when finished. Returns parsed marker plus
    launch/exit metadata. A timeout kills only the spawned process tree.
    """
    uproject_path = Path(uproject_path)
    script_path = Path(script_path)
    marker_path = Path(marker_path)
    exe = Path(UNREAL["cmd"]) if use_cmd else Path(UNREAL["editor"])
    if not exe.exists():
        return {"ok": False, "error": f"engine exe not found: {exe}"}
    if marker_path.exists():
        try:
            marker_path.unlink()
        except OSError:
            pass

    cmd = [
        str(exe),
        str(uproject_path),
        "-ExecutePythonScript=%s" % str(script_path),
        "-nosplash",
        "-nop4",
        "-noPIE",
        "-stdout",
        "-NoLogTimes",
    ] + (extra_args or [])
    if use_cmd:
        cmd.insert(7, "-unattended")
    # NOTE: without use_cmd (GUI editor) `-unattended` is deliberately NOT
    # added: an unattended editor never registers an OS-capturable window,
    # which is what the viewport screenshot leg depends on.
    log_path = marker_path.with_suffix(".log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("w", encoding="utf-8", errors="replace")
    env = dict(os.environ)
    if env_extra:
        env.update({str(k): str(v) for k, v in env_extra.items()})
    proc = None
    started = time.time()
    last_beat = 0.0
    try:
        proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT,
                                cwd=str(uproject_path.parent), env=env)
        marker_data: dict = {}
        while time.time() - started < timeout:
            if proc.poll() is not None:
                break
            if marker_path.exists():
                try:
                    marker_data = json.loads(marker_path.read_text(encoding="utf-8"))
                except Exception:
                    marker_data = {}
                # Editor-side python does not always terminate the engine
                # process; a short grace period lets it exit on its own.
                try:
                    proc.wait(timeout=12)
                except subprocess.TimeoutExpired:
                    pass
                break
            if time.time() - last_beat >= 15.0:
                last_beat = time.time()
                print(f"[ue_exec] waiting... {int(time.time() - started)}s "
                      f"(marker={'yes' if marker_path.exists() else 'no'})", flush=True)
            time.sleep(3.0)
        exited = proc.poll() is not None
        # Disposable test editor: kill our own tree when it does not exit.
        if proc.poll() is None:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, timeout=20)
        killed_after_marker = bool(marker_data) and proc.poll() is None
        timed_out = not bool(marker_data) and not exited
    finally:
        log_file.close()
        if proc is not None and proc.poll() is None:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, timeout=20)

    log_text = ""
    if log_path.exists():
        log_text = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
    return {
        "ok": bool(marker_data.get("ok")) and not timed_out,
        "exe": str(exe),
        "use_cmd": use_cmd,
        "marker": marker_data,
        "exited": exited,
        "killed_after_marker": killed_after_marker,
        "timed_out": timed_out,
        "elapsed_seconds": round(time.time() - started, 1),
        "log_tail": log_text,
        "log_path": str(log_path),
    }
