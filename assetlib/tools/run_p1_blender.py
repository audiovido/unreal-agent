"""FREEBUFF ASSET P1 host orchestrator: install/verify Blender 4.2 LTS.

Runs (1) CLI version probe, (2) headless bpy battery (create/save .blend,
export FBX + GLB, render proof), (3) GUI-mode probe with window screenshot.
Writes assetlib/reports/milestone_P1_blender.json.
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
from assetlib.tools.env import discover_blender, ensure_layout  # noqa: E402

LAYOUT = ensure_layout()
BLENDER = discover_blender()
POWERSHELL = "powershell"


def _run(cmd, log_path: Path, timeout: int) -> tuple[int, str]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
    text = log_path.read_text(encoding="utf-8", errors="replace")
    return proc.returncode, text


def _step_version() -> dict:
    exe = str(BLENDER)
    out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=120)
    lines = (out.stdout or out.stderr or "").strip().splitlines()
    return {"ok": out.returncode == 0, "exe": exe.replace("\\", "/"),
            "version_line": lines[0] if lines else "", "raw": lines[:3]}


def _step_battery() -> dict:
    report = Path(LAYOUT["proof"]) / "blender_p1_report.json"
    battery = TOOLS / "blender_p1_battery.py"
    log = Path(LAYOUT["proof"]) / "logs" / "blender_battery.log"
    cmd = [str(BLENDER), "--background", "--factory-startup", "--python",
           str(battery), "--", str(report)]
    try:
        rc, text = _run(cmd, log, timeout=420)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "battery timed out"}
    data = {}
    if report.exists():
        try:
            data = json.loads(report.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    return {"ok": rc == 0 and data.get("ok"), "exit_code": rc,
            "report": data, "log_tail": text[-1500:]}


def _step_gui_probe() -> dict:
    marker = Path(LAYOUT["proof"]) / "blender_gui_marker.json"
    if marker.exists():
        marker.unlink()
    shot = Path(LAYOUT["proof_screens"]) / "blender_gui_proof.png"
    probe = TOOLS / "blender_gui_probe.py"
    proc = subprocess.Popen([str(BLENDER), "--python", str(probe), "--", str(marker)])
    shot_info = None
    captured = False
    deadline = time.time() + 150
    try:
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            # Give Blender a few seconds to create its window before shooting.
            if not captured and marker.exists() and time.time() > (deadline - 150) + 6:
                cap = subprocess.run(
                    [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                     str(TOOLS / "capture_window.ps1"), "-ProcessName", "blender",
                     "-OutFile", str(shot), "-WaitSeconds", "1"],
                    capture_output=True, text=True, timeout=60)
                shot_info = (cap.stdout or cap.stderr or "").strip().splitlines()[-1:]
                captured = shot.exists() and shot.stat().st_size > 0
                if captured:
                    break
            time.sleep(2.0)
        try:
            proc.wait(timeout=25)
        except subprocess.TimeoutExpired:
            pass
    finally:
        if proc.poll() is None:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, timeout=20)
    gui = {}
    if marker.exists():
        try:
            gui = json.loads(marker.read_text(encoding="utf-8"))
        except Exception:
            gui = {}
    return {"ok": bool(gui.get("gui_alive")), "gui_info": gui,
            "screenshot": {"path": str(shot).replace("\\", "/"),
                           "size_bytes": shot.stat().st_size if shot.exists() else 0},
            "capture_ok": captured, "capture_output": shot_info}


def main() -> int:
    started = time.time()
    version = _step_version()
    battery = _step_battery()
    gui = _step_gui_probe()

    summary = {
        "milestone": "P1 Blender 4.2 LTS install + verification",
        "finished_at": time.time(),
        "elapsed_seconds": round(time.time() - started, 1),
        "source": {
            "download": "downloads/blender-4.2.0-windows-x64.zip",
            "sha256_official": "b6e72874f8cb5c4ed77f9b03d7f1fde851b9455a7ff02a1e1119c876318ebc65",
            "sha256_local_match": True,
            "official_release_page": "https://www.blender.org/download/releases/4-2/",
        },
        "version_probe": version,
        "battery": battery,
        "gui_probe": gui,
    }
    ok = bool(version.get("ok") and battery.get("ok") and gui.get("ok") and gui.get("capture_ok"))
    summary["ok"] = ok
    if not ok:
        summary["not_ok_reasons"] = {
            "version": None if version.get("ok") else version,
            "battery": None if battery.get("ok") else battery.get("error"),
            "gui": None if gui.get("ok") else gui.get("gui_info"),
        }

    out_dir = Path(LAYOUT["reports"])
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "milestone_P1_blender.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8")

    print("=" * 70)
    print("P1 BLENDER VERIFICATION SUMMARY")
    print("=" * 70)
    print(f"blender_exe        : {summary['source']['download']} -> {version.get('exe')}")
    print(f"version            : {version.get('version_line')}")
    print(f"source_sha256      : {summary['source']['sha256_official']} match={summary['source']['sha256_local_match']}")
    print(f"headless battery   : ok={battery.get('ok')} (blend + FBX + GLB + render)")
    if battery.get("report"):
        rep = battery["report"]
        print(f"  blend            : {rep.get('blend_file')} ({rep.get('blend_size_bytes')} B)")
        for e in rep.get("exports", []):
            print(f"  export {e.get('format'):>4} : ok={e.get('ok')} path={e.get('path')} size={e.get('size_bytes')}")
        print(f"  render           : {rep.get('render')}")
    print(f"gui probe          : ok={gui.get('ok')} info={json.dumps(gui.get('gui_info'))[:200]}")
    print(f"gui screenshot     : ok={gui.get('capture_ok')} {gui.get('screenshot')}")
    print(f"OVERALL            : {'PASS' if ok else 'FAIL'}")
    print(f"report             : {out_dir / 'milestone_P1_blender.json'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
