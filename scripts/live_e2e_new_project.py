#!/usr/bin/env python3
"""Phase 2/18 graduation: NEW-PROJECT E2E through the REAL API.

One natural-language request creates a brand new disposable project, opens it,
spawns a marker + light, saves the map, verifies read-back, captures proof and
reopens the persisted map. Then the probe restarts the Unreal Editor process,
waits for bridge-down, reopens the project through open_project (real editor
boot), and submits a NO-PATH request that must recover the project context and
verify the persisted marker + map. No manual intervention.

Usage: python scripts/live_e2e_new_project.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASE = "http://127.0.0.1:8765"
NAME = "UA_E2E_ClosedLoop_" + time.strftime("%Y%m%d_%H%M%S")
DEST = r"C:\Users\Shadow\Desktop\UnrealAgentGraduation"
UPP = rf"{DEST}\{NAME}\{NAME}.uproject"
ACTOR = "UA_E2E_Marker"
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(("PASS" if ok else "FAIL") + f" {name}" + (f" | {detail}" if detail else ""), flush=True)


def get_events(tid, since=0):
    ev = requests.get(BASE + "/api/events", timeout=20).json().get("events", [])
    return [e for e in ev if e.get("task_id") == tid]


def submit(task, timeout=30):
    r = requests.post(BASE + "/api/action", json={"action": "prompt", "payload": {"message": task}}, timeout=timeout)
    r.raise_for_status()
    body = r.json()
    tid = body.get("task_id") or (body.get("data") or {}).get("task_id")
    return tid


def wait_terminal(tid, timeout=900):
    tools = []
    terminal = None
    stall = None
    deadline = time.time() + timeout
    while time.time() < deadline:
        for e in get_events(tid):
            t = str(e.get("title") or "")
            if t.startswith("Running "):
                tools.append(t.replace("Running ", "").strip())
            if e.get("type") == "complete" or t == "COMPLETE":
                terminal = "COMPLETE"
            if "STALLED" in t or "EXECUTION_FAILED" in t or t == "BLOCKED":
                stall = stall or t
                terminal = terminal or "FAILED"
        if terminal:
            break
        time.sleep(2)
    return terminal, sorted(set(tools)), stall


def monitor_bridge_down(timeout=120):
    from tools.unreal.unreal_bridge import UnrealBridge
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not UnrealBridge(timeout=4).ping().get("ok"):
            return True
        time.sleep(1.5)
    return False


TASK1 = (
    f"Create a new disposable Unreal project named {NAME}, open it in Unreal Engine. "
    f"Create its default level, spawn a visible cube actor named {ACTOR} with a light, "
    f"save the level, verify the actor exists, then reopen the persisted map to confirm "
    f"it survives, and capture final proof."
)


def main():
    # ---- Task 1: full project lifecycle ----
    tid = submit(TASK1)
    check("task1 submitted", bool(tid), tid)
    terminal, tools, stall = wait_terminal(tid)
    check("task1 COMPLETE", terminal == "COMPLETE", f"terminal={terminal} stall={stall}")
    required = {"create_project", "inspect_project", "create_default_level", "get_project_identity", "spawn_actor", "save_level", "get_actor", "open_map", "capture_unreal_viewport"}
    missing = required - set(tools)
    check("task1 used full lifecycle tools", not missing, f"missing={sorted(missing)}")
    check("task1 no stall", stall is None, str(stall))

    # ---- verify filesystem + project identity ----
    p = Path(UPP)
    check("exact .uproject written", p.exists(), str(p))
    try:
        j = json.loads(p.read_text(encoding="utf-8-sig"))
        check("uproject EngineAssociation 5.x", str(j.get("EngineAssociation", "")).startswith("5."), j.get("EngineAssociation"))
        check("uproject enables bridge plugin", any(x.get("Name") == "UnrealAgentBridge" for x in j.get("Plugins", [])), "unrealagentbridge")
    except Exception as exc:
        check("uproject parse", False, str(exc))

    from tools.unreal.unreal_bridge import UnrealBridge
    bridge = UnrealBridge(timeout=30)
    ident = (bridge.get_project_identity().get("result") or {})
    check("bridge identity == new project", str(ident.get("project_name", "")).startswith("UA_E2E_ClosedLoop"), ident.get("project_name"))

    # ---- editor restart: kill the editor, wait bridge down, reopen ----
    check("killing editor for restart", True)
    try:
        import subprocess as sp
        ec = sp.run(["taskkill", "/IM", "UnrealEditor.exe", "/F"], capture_output=True, text=True, timeout=30)
        check("editor process killed", ec.returncode == 0, ec.stdout.strip()[:80])
    except Exception as exc:
        check("editor process killed", False, str(exc))
    check("bridge down after editor kill", monitor_bridge_down(120))

    from tools.unreal.project_manager import open_project
    opened = open_project(UPP)
    check("open_project reopens exact project", opened.get("ok") is True, json.dumps(opened)[:250])
    check("bridge identity after reopen", str((opened.get("project_identity") or {}).get("project_name", "")).startswith("UA_E2E_ClosedLoop"), json.dumps(opened.get("project_identity"))[:160])

    # ---- Task 2: NO-PATH request must recover context + verify persistence ----
    TASK2 = (
        f"Spawn a second cube named {ACTOR}_2 next to the marker, save the level, "
        f"verify both the marker {ACTOR} and {ACTOR}_2 exist, then capture proof."
    )
    tid2 = submit(TASK2)
    check("task2 (no-path) submitted", bool(tid2), tid2)
    terminal2, tools2, stall2 = wait_terminal(tid2)
    check("task2 COMPLETE after editor restart", terminal2 == "COMPLETE", f"terminal={terminal2} stall={stall2}")
    check("task2 recovered context (no PROJECT_CONTEXT_MISSING)", "inspect_project" in tools2 and stall2 is None, f"tools={tools2[:6]}")
    check("task2 verified persisted actor", f"get_actor" in tools2, str(tools2))

    failed = [n for n, ok in results if not ok]
    print("NEW_PROJECT_E2E_LIVE:", "PASS" if not failed else f"FAIL ({len(failed)})", flush=True)
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()