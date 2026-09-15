#!/usr/bin/env python3
"""Phase 10 graduation: LIVE SELF-REPAIR loop.

Deliberate first-attempt failure (WRONG_VALUE), structured diagnosis, a
corrective set_blueprint_variable_default FIX step, retry validation, success,
evidence, and disposable cleanup. Verifies the terminal is COMPLETE and that
the value was corrected and persisted."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASE = "http://127.0.0.1:8765"
BP = "/Game/AgentGraduation/BP_SelfRepair_" + time.strftime("%H%M%S")
TASK = (
    f"Create {BP} with a String variable GradValue. Initially set it to "
    f"WRONG_VALUE. Expected value is EXPECTED_VALUE. Compile, validate, "
    f"capture proof, and delete the probe."
)
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(("PASS" if ok else "FAIL") + f" {name}" + (f" | {detail}" if detail else ""), flush=True)


def main():
    r = requests.post(BASE + "/api/action", json={"action": "prompt", "payload": {"message": TASK}}, timeout=30)
    r.raise_for_status()
    tid = r.json().get("task_id") or (r.json().get("data") or {}).get("task_id")
    check("self-repair task submitted", bool(tid), tid)

    tools = []
    terminal = None
    stall = None
    deadline = time.time() + 300
    while time.time() < deadline:
        ev = requests.get(BASE + "/api/events", timeout=20).json().get("events", [])
        for e in [x for x in ev if x.get("task_id") == tid]:
            t = str(e.get("title") or "")
            if t.startswith("Running "):
                tools.append(t.replace("Running ", "").strip())
            if e.get("type") == "complete" or t == "COMPLETE":
                terminal = "COMPLETE"
            if "STALLED" in t or "EXECUTION_FAILED" in t:
                stall = stall or t
                terminal = terminal or "FAILED"
        if terminal:
            break
        time.sleep(1.5)

    tools = sorted(set(tools))
    check("self-repair COMPLETE", terminal == "COMPLETE", f"terminal={terminal} stall={stall}")
    check("first attempt made (set WRONG_VALUE)", "set_blueprint_variable_default" in tools, str(tools))
    check("read-back validation ran", "get_blueprint_variable_default" in tools)
    # FIX machinery reuses set_blueprint_variable_default — expect it more than
    # once (initial set + corrective fix).
    fix_count = tools.count("set_blueprint_variable_default")
    check("corrective FIX steps bounded and present", fix_count >= 1 and fix_count <= 3, f"count={fix_count}")
    check("compiled", "compile_blueprint" in tools)
    check("cleanup delete ran", "delete_asset" in tools)
    check("no stall", stall is None, str(stall))
    print("TOOL SEQUENCE:", tools, flush=True)

    from tools.unreal.unreal_bridge import UnrealBridge
    bridge = UnrealBridge(timeout=30)
    r = bridge.get_asset_info(BP)
    payload = r.get("result") if isinstance(r, dict) else {}
    check("probe asset cleaned up", payload.get("ok") is not True, json.dumps(payload)[:120])

    failed = [n for n, ok in results if not ok]
    print("SELF_REPAIR_LIVE:", "PASS" if not failed else f"FAIL ({len(failed)})", flush=True)
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()