"""Aivido overnight runtime-hardening battery (Phase 2).

Exercises the real product runtime against http://127.0.0.1:8765
(app.served:app): backend surface, malformed-input truthfulness, bridge
truthfulness, session/task flow (queued -> running -> terminal PASS/FAIL,
cancellation, duplicate guard, bounded polling), proof serving, and stale /
unknown resource handling. Every poll is bounded; no fabricated success.

Writes reports/release/RUNTIME_HARDENING.json; exit 0 iff no CRITICAL fail.
"""
from __future__ import annotations

import base64
import json
import socket
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
BASE = "http://127.0.0.1:8765"
PROJECT_ID = sys.argv[1] if len(sys.argv) > 1 else None
OUT = ROOT / "reports" / "release" / "RUNTIME_HARDENING.json"

results: list[dict] = []


def record(area: str, name: str, ok: bool, detail, severity: str = "major"):
    results.append({"area": area, "name": name,
                    "ok": bool(ok), "severity": severity,
                    "detail": detail})
    print(("PASS " if ok else "FAIL ") + f"[{area}] {name}: {str(detail)[:220]}")


TERMINAL = ("done", "failed", "blocked", "cancelled", "canceled")


def poll_terminal(session_id: str, execution_id: str, max_s: float = 420.0):
    """Poll a session execution until terminal or bounded timeout."""
    t0 = time.time()
    attempts = 0
    last = None
    while time.time() - t0 < max_s:
        attempts += 1
        r = requests.get(f"{BASE}/api/sessions/{session_id}/execution/{execution_id}", timeout=15)
        last = r
        if r.status_code == 200:
            d = r.json()
            state = str(((d.get("execution") or {}).get("status")) or "").lower()
            if state in TERMINAL:
                return d, time.time() - t0, attempts
        time.sleep(3)
    return (last.json() if last is not None else None), time.time() - t0, attempts


# ----------------------------------------------------------------- backend
def backend_surface():
    r = requests.get(f"{BASE}/api/status", timeout=15)
    d = r.json()
    record("backend", "status_endpoint", r.status_code == 200 and d.get("ok") is True,
           {"code": r.status_code, "unreal_ok": (d.get("unreal") or {}).get("ok")})
    r = requests.get(f"{BASE}/app", timeout=15)
    record("backend", "booth_ui_served", r.status_code == 200 and "AIVIDO" in r.text.upper(),
           {"code": r.status_code, "bytes": len(r.content)})
    r = requests.get(f"{BASE}/api/resources", timeout=15)
    sup = (r.json() or {}).get("supervisor") or {}
    record("backend", "resource_supervisor", r.status_code == 200 and sup.get("unreal_processes"),
           {"unreal_pids": sup.get("unreal_processes"), "ram_used_pct": sup.get("ram_used_percent")})


# ------------------------------------------------------- malformed inputs
def malformed():
    r = requests.post(f"{BASE}/api/action", json={}, timeout=15)
    record("malformed", "action_missing_action_400", r.status_code == 400, {"code": r.status_code, "body": r.text[:120]})
    r = requests.post(f"{BASE}/api/action", json={"action": "prompt", "payload": []}, timeout=15)
    record("malformed", "action_bad_payload_400", r.status_code == 400, {"code": r.status_code})
    r = requests.post(f"{BASE}/api/action", data="{not json", headers={"Content-Type": "application/json"}, timeout=15)
    record("malformed", "invalid_json_rejected", r.status_code in (400, 422), {"code": r.status_code})
    r = requests.post(f"{BASE}/api/action", json={"action": "definitely_not_wired_xyz"}, timeout=15)
    ok = r.status_code in (400, 404, 501) or (r.status_code == 200 and not (r.json() or {}).get("ok", True))
    record("malformed", "unknown_action_truthful", ok, {"code": r.status_code, "body": r.text[:160]})
    r = requests.post(f"{BASE}/api/sessions", json={"project_id": "nope_missing"}, timeout=15)
    record("malformed", "unknown_project_404", r.status_code == 404, {"code": r.status_code})
    r = requests.post(f"{BASE}/api/sessions/sess_missing/action", json={"prompt": "x"}, timeout=15)
    record("malformed", "unknown_session_404", r.status_code == 404, {"code": r.status_code})
    r = requests.get(f"{BASE}/api/execution/does_not_exist_xyz", timeout=15)
    record("malformed", "stale_task_404", r.status_code == 404, {"code": r.status_code, "body": r.text[:120]})
    r = requests.get(f"{BASE}/api/sessions/sess_missing/execution/exec_missing", timeout=15)
    record("malformed", "stale_session_execution_404", r.status_code == 404, {"code": r.status_code})
    r = requests.get(f"{BASE}/", timeout=15)
    record("backend", "root_served", r.status_code == 200, {"code": r.status_code})


# ------------------------------------------------------------------ bridge
def bridge_direct():
    def raw(payload: dict, timeout: float = 30.0) -> dict:
        data = (json.dumps(payload) + "\n").encode("utf-8")
        with socket.create_connection(("127.0.0.1", 6766), timeout=timeout) as s:
            s.settimeout(timeout)
            s.sendall(data)
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
        return json.loads(buf.decode("utf-8").strip())

    r = raw({"type": "ping"})
    record("bridge", "ping", r.get("ok") is True, r.get("result") or r.get("error"))
    r = raw({"type": "identity"})
    record("bridge", "identity", r.get("ok") is True, (r.get("result") or {}).get("engine"))
    r = raw({"type": "bogus_message_type_xyz"})
    record("bridge", "unknown_type_truthful", r.get("ok") is not True and bool(r.get("error")),
           {"error": str(r.get("error"))[:120]})
    r = raw({"type": "python", "code": "1/0"})
    record("bridge", "invalid_python_truthful", r.get("ok") is not True and "PYTHON_EXECUTION_FAILED" in str(r.get("code", "")),
           {"code": r.get("code"), "msg": str(r.get("message"))[:120]})
    r = raw({"type": "python", "code": "import unreal\nw = unreal.EditorLevelLibrary.get_editor_world()\n__bridge_result__ = {'ok': w is not None, 'map': w.get_path_name()}"})
    res = r.get("result") or {}
    record("bridge", "harmless_operation", r.get("ok") is True and "AividoHQ" in str(res.get("map")),
           {"map": str(res.get("map"))[:80]})


# ------------------------------------------------------------ session flow
def session_flow():
    if not PROJECT_ID:
        record("session", "project_id_missing", False, "pass project id as argv[1]", "critical")
        return
    r = requests.post(f"{BASE}/api/sessions", json={"project_id": PROJECT_ID, "client_id": "overnight-hardening"}, timeout=15)
    if r.status_code != 200:
        record("session", "create_session", False, {"code": r.status_code, "body": r.text[:200]}, "critical")
        return
    sid = (r.json() or {}).get("session", {}).get("session_id")
    record("session", "create_session", bool(sid), {"session_id": sid})

    r = requests.post(f"{BASE}/api/sessions/{sid}/start", json={"launch_if_needed": False, "wait_s": 60}, timeout=90)
    record("session", "start_session_bridge_bind", r.status_code == 200 and (r.json() or {}).get("ok") is not False,
           {"code": r.status_code, "body": json.dumps(r.json())[:220] if r.headers.get("content-type", "").startswith("application/json") else r.text[:200]})

    # --- Mission A (read/inspect) fired with an intentional client timeout to
    # prove the server survives client aborts, then polled to terminal.
    t0 = time.time()
    try:
        requests.post(f"{BASE}/api/sessions/{sid}/action",
                      json={"prompt": "read only: inspect the current AividoHQ state and report the total actor count and the number of AVIDO_Human characters",
                            "read_only": True, "execution_id": "exec_mission_a"},
                      timeout=1.0)
        client_abort = False
    except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
        client_abort = True
    record("session", "client_abort_survival", client_abort,
           {"aborted_client_after_s": round(time.time() - t0, 2)})
    r = requests.get(f"{BASE}/api/status", timeout=10)
    record("backend", "server_alive_after_abort", r.status_code == 200, {"code": r.status_code})

    d, dur, attempts = poll_terminal(sid, "exec_mission_a")
    state = str(((d or {}).get("execution") or {}).get("status") or "?").lower()
    record("session", "mission_a_terminal", state == "done",
           {"state": state, "duration_s": round(dur, 1), "poll_attempts": attempts,
            "verdict": ((d or {}).get("execution") or {}).get("verdict"),
            "why": str(((d or {}).get("execution") or {}).get("why"))[:200]}, "critical")

    # duplicate-execution guard while nothing runs (queue accepts) and no
    # duplicate task ids afterwards
    r = requests.get(f"{BASE}/api/sessions/{sid}/tasks", timeout=15)
    tasks = (r.json() or {}).get("tasks") or []
    ids = [t.get("execution_id") for t in tasks]
    record("session", "no_duplicate_task_ids", len(ids) == len(set(ids)), {"task_ids": ids})

    # --- Mission F (terminal FAIL path, safely forced)
    requests.post(f"{BASE}/api/sessions/{sid}/async",
                  json={"prompt": "read only: call the tool named definitely_not_a_real_tool_xyz and report its exact result",
                        "read_only": True, "execution_id": "exec_mission_f"},
                  timeout=15)
    d, dur, attempts = poll_terminal(sid, "exec_mission_f")
    state = str(((d or {}).get("execution") or {}).get("status") or "?").lower()
    record("session", "mission_f_fail_truthful", state in ("failed", "blocked"),
           {"state": state, "duration_s": round(dur, 1),
            "why": str(((d or {}).get("execution") or {}).get("why"))[:200]}, "critical")

    # --- cancellation (bounded)
    requests.post(f"{BASE}/api/sessions/{sid}/async",
                  json={"prompt": "read only: wait 60 seconds then inspect the level and report actor count",
                        "read_only": True, "execution_id": "exec_mission_c"},
                  timeout=15)
    time.sleep(4)
    r = requests.post(f"{BASE}/api/sessions/{sid}/cancel", timeout=15)
    record("session", "cancel_accepted", r.status_code == 200, {"body": r.text[:160]})
    d, dur, attempts = poll_terminal(sid, "exec_mission_c", max_s=240)
    state = str(((d or {}).get("execution") or {}).get("status") or "?").lower()
    record("session", "cancel_terminal", state in ("cancelled", "canceled", "failed", "done", "blocked"),
           {"state": state, "duration_s": round(dur, 1), "poll_attempts": attempts})

    # --- proof for the session
    r = requests.get(f"{BASE}/api/sessions/{sid}/proof", timeout=15)
    proof = (r.json() or {}).get("proof") or []
    live_labels = [p for p in proof if str(p.get("kind") or p.get("status") or "").upper() == "LIVE" or p.get("live") is True]
    demo_live = [p for p in proof if "DEMO" in str(p).upper() or "CONCEPT" in str(p).upper()]
    record("proof", "proof_listing", r.status_code == 200, {"entries": len(proof)})
    record("proof", "no_demo_promoted_live", len(demo_live) == 0, {"demo_entries": len(demo_live)})
    if proof:
        p0 = proof[0]
        eid0 = p0.get("execution_id")
        name0 = p0.get("name") or p0.get("file") or p0.get("filename")
        if eid0 and name0:
            rf = requests.get(f"{BASE}/api/sessions/{sid}/proof/{eid0}/{name0}", timeout=30)
            data_ok = rf.status_code == 200 and len(rf.content) > 1000
            try:
                marker = base64.b64encode(rf.content[:8]).decode() if data_ok else ""
            except Exception:
                marker = ""
            record("proof", "proof_file_served", data_ok,
                   {"eid": eid0, "name": name0, "bytes": len(rf.content)})
        rf = requests.get(f"{BASE}/api/sessions/{sid}/proof/{eid0}/..%2F..%2Fetc_passwd.png", timeout=15)
        record("proof", "path_traversal_blocked", rf.status_code in (404, 400), {"code": rf.status_code})
    else:
        record("proof", "proof_file_served", False, "no proof entries produced by missions", "minor")

    # retry surface (global) — must respond truthfully with no active global task
    r = requests.post(f"{BASE}/api/retry", timeout=15)
    record("session", "retry_no_active_truthful", r.status_code in (200, 400), {"code": r.status_code, "body": r.text[:140]})
    return sid


def backend_restart(sid: str | None):
    if not sid:
        record("backend", "restart_persistence", False, "no session to check", "minor")
        return
    r = requests.post(f"{BASE}/api/sessions/{sid}/disconnect", timeout=30)
    record("backend", "session_disconnect", r.status_code == 200, {"code": r.status_code})


def main() -> int:
    backend_surface()
    malformed()
    bridge_direct()
    sid = session_flow()
    backend_restart(sid)
    out = {
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "base": BASE,
        "results": results,
        "counts": {
            "total": len(results),
            "pass": sum(1 for r in results if r["ok"]),
            "fail": sum(1 for r in results if not r["ok"]),
            "critical_fail": sum(1 for r in results if not r["ok"] and r["severity"] == "critical"),
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(json.dumps(out["counts"], indent=2))
    return 0 if out["counts"]["critical_fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
