"""FREEBUFF ASSET P1: Unreal smoke-import driver (two passes + OS capture).

Pass A (headless UnrealEditor-Cmd): import FBX + GLB into /Game/Smoke,
verify/spawn meshes, save the level.  (Skipped when a successful pass A
record already exists.)
Pass B (GUI UnrealEditor): load the map, verify meshes in the level, frame the
viewport.
Then the OS window of the disposable editor is captured to a PNG proof.

All output stays under assetlib/tests/ue/.
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
from assetlib.tools.env import ensure_layout  # noqa: E402
from assetlib.tools.ue_exec import run_ue_python  # noqa: E402
from assetlib.tools.ue_project import create_ue_project  # noqa: E402

LAYOUT = ensure_layout()
PROJECT_NAME = "ASSET_P1_Smoke"
MARKER_A = Path(LAYOUT["tests_ue"]) / "p1_passA_done.json"
MARKER_B = Path(LAYOUT["tests_ue"]) / "p1_passB_done.json"
SHOT = Path(LAYOUT["proof_screens"]) / "ue_smoke_viewport.png"


def _env(marker: Path, fbx: Path, glb: Path) -> dict:
    env = dict(os.environ)
    env["ASSETLIB_MARKER"] = str(marker)
    env["ASSETLIB_FBX"] = str(fbx)
    env["ASSETLIB_GLB"] = str(glb)
    return env


def _kill_our_editors():
    """Defensively stop only UnrealEditor processes running OUR disposable
    project (identified by the project name in the command line)."""
    import csv
    import io

    out = subprocess.run(["wmic", "process", "where",
                          f"name like '%UnrealEditor%'", "get",
                          "ProcessId,CommandLine", "/format:csv"],
                         capture_output=True, text=True, timeout=30)
    pids = []
    for row in csv.reader(io.StringIO(out.stdout)):
        if len(row) >= 3 and PROJECT_NAME in (row[2] or ""):
            pid = row[1]
            if pid and pid.isdigit():
                pids.append(int(pid))
    for pid in pids:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, timeout=20)
    if pids:
        print(f"stopped {len(pids)} stale editor(s) from previous runs", flush=True)


def _rm_quiet(p: Path):
    try:
        p.unlink(missing_ok=True)
    except OSError:
        pass


def _pass_a(created: dict, fbx: Path, glb: Path) -> dict:
    # Reuse an already-successful import record.
    if MARKER_A.exists():
        try:
            prev = json.loads(MARKER_A.read_text(encoding="utf-8"))
            if prev.get("ok") and prev.get("verified"):
                return {"ok": True, "reused": True, "marker": prev,
                        "elapsed_seconds": 0.0}
        except Exception:
            pass
    _rm_quiet(MARKER_A)
    _rm_quiet(MARKER_A.with_suffix(".log"))
    return run_ue_python(
        created["uproject_path"], TOOLS / "ue_smoke_import.py", MARKER_A,
        use_cmd=True, timeout=600,
        env_extra=_env(MARKER_A, fbx, glb),
    )


def _pass_b(created: dict) -> dict:
    _rm_quiet(MARKER_B)
    _rm_quiet(MARKER_B.with_suffix(".log"))
    return run_ue_python(
        created["uproject_path"], TOOLS / "ue_shot.py", MARKER_B,
        use_cmd=False, timeout=600,
        env_extra={"ASSETLIB_MARKER": str(MARKER_B)},
    )


def _os_capture() -> dict:
    if SHOT.exists():
        SHOT.unlink()
    cap = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(TOOLS / "capture_window.ps1"), "-ProcessName", "UnrealEditor",
         "-TitleMatch", f"*{PROJECT_NAME}*", "-OutFile", str(SHOT),
         "-WaitSeconds", "1"],
        capture_output=True, text=True, timeout=90)
    out = (cap.stdout or cap.stderr or "").strip().splitlines()[-1:]
    return {"ok": SHOT.exists() and SHOT.stat().st_size > 0,
            "path": str(SHOT).replace("\\", "/"),
            "size_bytes": SHOT.stat().st_size if SHOT.exists() else 0,
            "ps_output": out}


def main() -> int:
    started = time.time()
    fbx = Path(LAYOUT["tests_blender"]) / "exports" / "P1_TableTop.fbx"
    glb = Path(LAYOUT["tests_blender"]) / "exports" / "P1_TableTop.glb"
    if not (fbx.exists() and glb.exists()):
        print(f"missing blender exports: fbx={fbx.exists()} glb={glb.exists()}")
        return 1

    _kill_our_editors()
    dest = Path(LAYOUT["tests_ue"]) / PROJECT_NAME
    if not dest.exists():
        created = create_ue_project(PROJECT_NAME)
        if not created.get("ok"):
            print(json.dumps(created, indent=2))
            return 1
    else:
        created = {
            "ok": True, "project_name": PROJECT_NAME,
            "project_root": str(dest),
            "uproject_path": str(dest / f"{PROJECT_NAME}.uproject"),
        }
    print("project:", created["uproject_path"], flush=True)

    result_a = _pass_a(created, fbx, glb)
    ma = result_a.get("marker") or {}
    print("PASS A (Cmd import):", json.dumps({
        "ok": result_a.get("ok"), "reused": result_a.get("reused", False),
        "elapsed": result_a.get("elapsed_seconds"),
        "verified": ma.get("verified"),
    }, default=str)[:900], flush=True)

    result_b = _pass_b(created)
    mb = result_b.get("marker") or {}
    print("PASS B (GUI verify):", json.dumps({
        "ok": result_b.get("ok"), "elapsed": result_b.get("elapsed_seconds"),
        "level_actors": mb.get("level_actors"),
    }, default=str)[:900], flush=True)

    capture = _os_capture()
    print("OS capture:", json.dumps(capture)[:400], flush=True)

    ok = bool(result_a.get("ok") and result_b.get("ok") and capture.get("ok")
              and (mb.get("viewport_ready") is True))
    summary = {
        "ok": ok,
        "project": created,
        "blender_exports": {"fbx": str(fbx), "glb": str(glb)},
        "pass_a_cmd_import": result_a,
        "pass_b_gui_verify": result_b,
        "os_capture": capture,
        "elapsed_seconds": round(time.time() - started, 1),
    }
    out = Path(LAYOUT["reports"]) / "milestone_P1_unreal.json"
    out.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    print("=" * 70)
    print("P1 UNREAL SMOKE IMPORT SUMMARY")
    print("=" * 70)
    print(f"project            : {created['uproject_path']}")
    print(f"pass A (Cmd import): ok={result_a.get('ok')} "
          f"elapsed={result_a.get('elapsed_seconds')}s")
    for v in ma.get("verified") or []:
        print(f"  verified {v.get('label'):>5} : class={v.get('class')} "
              f"size_cm={v.get('size_cm')} ok={v.get('ok')}")
    print(f"pass B (GUI verify): ok={result_b.get('ok')} "
          f"elapsed={result_b.get('elapsed_seconds')}s")
    print(f"  level actors     : {json.dumps(mb.get('level_actors'))[:400]}")
    print(f"  viewport_ready   : {mb.get('viewport_ready')}")
    print(f"OS capture         : ok={capture.get('ok')} {capture.get('path')} "
          f"bytes={capture.get('size_bytes')}")
    if not ok:
        print("errors:", json.dumps({
            "a_marker": ma.get("error"), "b_fatal": mb.get("fatal"),
            "capture": capture.get("ps_output"),
            "b_log_tail": (result_b.get("log_tail") or "")[-300:],
        }, default=str)[:1600])
    print(f"OVERALL            : {'PASS' if ok else 'FAIL'}")
    print(f"report             : {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
