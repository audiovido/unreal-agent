"""PHASE 1 REPRO — isolated_capture_mission (ONE run, bounded).

Starts the exact QA capture prompt against the LIVE backend and polls the
mission checkpoint, collecting: mission id, status transitions, current step,
step results, evidence, cancel state. Never re-submits.
"""
from __future__ import annotations

import json
import sys
import time

import requests

BASE = "http://127.0.0.1:8765"
PROMPT = "read-only diagnostic: capture a screenshot of the current level"

out = {
    "repro_started_at": time.time(),
    "prompt": PROMPT,
    "events": [],
}


def log(kind, **kw):
    rec = {"at": round(time.time() - out["repro_started_at"], 2), "kind": kind}
    rec.update(kw)
    out["events"].append(rec)
    print(f"[{rec['at']:8.2f}s] {kind}: {json.dumps({k: v for k, v in kw.items() if k != 'body'}, default=str)[:400]}")


def main():
    r = requests.post(
        f"{BASE}/api/unreal-coder/async",
        json={"prompt": PROMPT, "mode": "execute", "read_only": True},
        timeout=40,
    )
    body = r.json()
    mid = body.get("mission_id")
    log("accepted", response=body)
    if not mid:
        log("no_mission_id", raw=r.text[:500])
        sys.exit(1)
    out["mission_id"] = mid

    last = None
    start = time.time()
    while time.time() - start < 150:
        resp = requests.get(f"{BASE}/api/unreal-coder/mission/{mid}", timeout=20)
        m = resp.json()
        status = m.get("status")
        completed = len(m.get("completed_work", {}).get("step_ids") or [])
        total = (m.get("completed_work") or {}).get("steps_total")
        verdict = m.get("verdict")
        sig = (status, completed, verdict)
        if sig != last:
            log(
                "transition",
                status=status,
                steps=f"{completed}/{total}",
                verdict=verdict,
                why=(m.get("why") or "")[:200],
                step_results_ok={
                    k: (v.get("ok") if isinstance(v, dict) else v)
                    for k, v in (m.get("step_results") or {}).items()
                } or None,
            )
            last = sig
            out["last_payload"] = {
                "status": status,
                "verdict": verdict,
                "completed": completed,
                "total": total,
                "why": m.get("why"),
                "evidence": m.get("evidence"),
                "resumable": m.get("resumable"),
            }
        if status in ("complete", "failed", "blocked", "cancelled"):
            log("terminal", status=status, verdict=verdict)
            out["terminal"] = out["last_payload"]
            break
        time.sleep(5)

    # Snapshot the final raw checkpoint regardless.
    resp = requests.get(f"{BASE}/api/unreal-coder/mission/{mid}", timeout=20)
    out["final_checkpoint"] = resp.json()
    with open("memory/qa/repro_isolated_capture_mission.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, default=str)
    print("WROTE memory/qa/repro_isolated_capture_mission.json")


if __name__ == "__main__":
    main()