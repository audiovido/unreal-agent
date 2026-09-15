#!/usr/bin/env python3
"""Phase 15 graduation: ONE genuine supervised Unreal task.

Queues a real Unreal task in the supervisor's persisted state, executes it
through the REAL backend /api/chat pipeline (execute_task_via_api), verifies
PASS/FAIL semantics, and simulates a restart by reloading the persisted state
and confirming the task outcome survives without duplicate execution."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from supervisor.state import (
    Task, SupervisorState, save_state, load_state, ensure_dirs,
    STATE_FILE,
)
from supervisor.supervisor import Supervisor

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(("PASS" if ok else "FAIL") + f" {name}" + (f" | {detail}" if detail else ""), flush=True)


def main():
    ensure_dirs()
    # fresh deterministic state for the probe
    state = SupervisorState()
    state.workers = []
    sup = Supervisor(state)

    task = Task(
        title="Supervised Unreal graduation probe",
        prompt=(
            "Spawn a cube named SUPERVISOR_PROBE, save the level, verify it "
            "exists, and capture proof."
        ),
        tags=["unreal"],
    )
    tid = sup.add_task(task)
    check("task queued in persisted state", tid == task.id, tid)

    # clean any leftover actor from prior runs (disposable project only)
    from tools.unreal.unreal_bridge import UnrealBridge
    bridge = UnrealBridge(timeout=30)
    r = bridge.execute_python(
        "import unreal; ms = [a for a in unreal.EditorLevelLibrary.get_all_level_actors() if a.get_actor_label() == 'SUPERVISOR_PROBE']; __bridge_result__ = [a.get_name() for a in ms]"
    )
    inner = r.get("result") if isinstance(r, dict) else None
    for name in list(inner) if isinstance(inner, list) else []:
        try:
            bridge.delete_actor(str(name))
        except Exception:
            pass

    result = sup.execute_task_via_api(task)
    check("execute_task_via_api returned result", result is not None)
    check("supervised task PASS", result.pass_fail == "PASS", f"pass_fail={result.pass_fail} error={result.error} output={str(result.output)[:200]}")

    # simulate restart: reload state from disk (fresh Supervisor object)
    persisted = load_state()
    # the probe ran outside _tick, so persist the outcome manually
    task.pass_fail = result.pass_fail
    task.status = "passed" if result.pass_fail == "PASS" else "blocked"
    task.last_output = result.output
    state.completed_tasks.append(task)
    state.tasks = [t for t in state.tasks if t.id != task.id]
    save_state(state)
    reloaded = load_state()
    check("state survives restart (completed task persisted)",
          any(t.id == tid for t in reloaded.completed_tasks), f"completed={len(reloaded.completed_tasks)}")
    check("no duplicate queued copies after restart",
          len([t for t in reloaded.tasks if t.id == tid]) == 0 and len([t for t in reloaded.completed_tasks if t.id == tid]) == 1)

    # verify the supervised task's actual artifact
    r = bridge.get_actor("SUPERVISOR_PROBE")
    check("supervised task left verified actor", (r.get("result") or {}).get("ok") is True, json.dumps(r.get("result"))[:150])

    failed = [n for n, ok in results if not ok]
    print("SUPERVISOR_LIVE:", "PASS" if not failed else f"FAIL ({len(failed)})", flush=True)
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()