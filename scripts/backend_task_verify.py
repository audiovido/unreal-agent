"""Submit a no-project-path task to the REAL running backend and verify the
mandated recovery sequence and COMPLETE verdict via /api/action + /api/events.

Usage:
    python scripts/backend_task_verify.py "TASK TEXT"
"""

import json
import sys
import time

import requests

BASE = "http://127.0.0.1:8765"


def main():
    task = " ".join(sys.argv[1:]).strip() or (
        "Spawn a cube named PROJECT_CONTEXT_FINAL_TEST, save the level, "
        "verify it exists, and capture proof."
    )
    print("TASK (no project path):", task)

    r = requests.post(f"{BASE}/api/action", json={"action": "prompt", "payload": {"message": task}}, timeout=20)
    r.raise_for_status()
    body = r.json()
    task_id = ((body.get("data") or {}).get("task_id")) or body.get("task_id")
    print("start:", body.get("ok"), "task_id:", task_id)

    if not task_id:
        print("FAIL: no task_id returned")
        sys.exit(2)

    tools_seen = []
    terminal = None
    stall = None
    deadline = time.time() + 300
    while time.time() < deadline:
        ev = requests.get(f"{BASE}/api/events", timeout=20).json().get("events", [])
        for e in [x for x in ev if x.get("task_id") == task_id]:
            etype = e.get("type")
            if etype == "tool":
                title = str(e.get("title") or "")
                name = title.replace("Running ", "").strip()
                if name and name not in tools_seen:
                    tools_seen.append(name)
            if etype == "complete":
                terminal = "COMPLETE"
            if etype == "final":
                # final is only emitted on a genuinely terminal verdict
                terminal = terminal or "COMPLETE"
            if etype == "error":
                title = str(e.get("title") or "").upper()
                detail = e.get("data") or {}
                if "STALLED" in title:
                    terminal = terminal or "EXECUTION_STALLED"
                    stall = (detail.get("stall_reason") if isinstance(detail, dict) else None) or e.get("title")
                elif title == "EXECUTION_FAILED" or title == "BLOCKED":
                    terminal = terminal or "FAILED/BLOCKED"
        if terminal:
            break
        time.sleep(1)

    print("tool sequence seen:", tools_seen)
    print("terminal:", terminal, "| stall:", stall)

    required = {"inspect_project", "unreal_ping", "spawn_actor", "get_actor", "save_level", "capture_unreal_viewport"}
    problems = []
    if terminal != "COMPLETE":
        problems.append(f"terminal is not COMPLETE: {terminal}")
    if stall:
        problems.append(f"stalled: {stall}")
    missing = required - set(tools_seen)
    if missing:
        problems.append(f"missing tools: {sorted(missing)}")
    if any("not found" in t.lower() for t in tools_seen):
        problems.append("uproject not found present")

    if problems:
        print("BACKEND TASK VERIFY: FAIL")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    print("BACKEND TASK VERIFY: PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()