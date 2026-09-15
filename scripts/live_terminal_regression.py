"""Live regression: terminal-state core fix.

Posts the exact user task through the same /api/action endpoint the Freebuff
router uses, then watches the returned task's events for a deterministic
terminal verdict (COMPLETE == PASS) vs EXECUTION_STALLED.

Expected on a fixed backend:
  inspect_project -> spawn_actor -> save_level -> get_actor(read-back) -> COMPLETE
  NO EXECUTION_STALLED.
"""
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8765"
ACTOR = sys.argv[1] if len(sys.argv) > 1 else "TERMINAL_STATE_FINAL_TEST"
TASK = (
    "Spawn a cube named " + ACTOR + ", "
    "save the level, and verify it exists."
)


def _get(url, timeout):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _post(url, body, timeout):
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def submit():
    try:
        data = _post(BASE + "/api/action",
                     {"action": "prompt", "payload": {"message": TASK}},
                     timeout=200)
    except Exception as exc:  # noqa: BLE001
        return None, f"submit failed: {exc}"
    if not data or data.get("ok") is not True:
        return None, f"submit rejected: {data or 'no data'}"
    tid = data.get("task_id") or (data.get("data") or {}).get("task_id")
    return tid, None


def main():
    tid, err = submit()
    if err or not tid:
        print("RESULT: STALL", {"error": err})
        return 2

    tools = []
    final = None
    stall = None
    deadline = time.time() + 300
    print(f"task_id={tid}", flush=True)
    while time.time() < deadline:
        try:
            evs = _get(BASE + "/api/events", 10).get("events", [])
        except Exception:  # noqa: BLE001
            time.sleep(1.5)
            continue
        mine = [e for e in evs if e.get("task_id") == tid]
        for ev in mine:
            et = ev.get("type")
            title = ev.get("title") or ""
            status = ev.get("status") or ""
            det = ev.get("detail")
            if et == "tool_result":
                tools.append(ev)
            if title == "EXECUTION_STALLED" or title == "EXECUTION_FAILED":
                stall = {"title": title, "stall_reason": (det or {}).get("stall_reason") if isinstance(det, dict) else det, "detail": det}
            if et == "final":
                final = {"status": status, "title": title}
            if et == "error" and "EXECUTION" in title:
                stall = stall or {"title": title, "detail": det}
        if stall:
            print("TOOL_SEQUENCE:", [ (t.get("title"), t.get("status")) for t in tools ])
            print("RESULT: STALL", json.dumps(stall))
            return 3
        if final and final["status"] == "complete":
            print("TOOL_SEQUENCE:", [ (t.get("title"), t.get("status")) for t in tools ])
            print("RESULT: PASS", json.dumps(final))
            return 0
        time.sleep(1.5)

    print("TOOL_SEQUENCE:", [ (t.get("title"), t.get("status")) for t in tools ])
    print("RESULT: NO_TERMINAL_IN_TIMEOUT", {"final": final, "stall": stall})
    return 4


if __name__ == "__main__":
    sys.exit(main())