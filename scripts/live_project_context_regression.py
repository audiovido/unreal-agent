"""Live regression for the Unreal Agent PROJECT CONTEXT CORE FIX.

Drives the real deterministic execution engine against the actually-open Unreal
Editor bridge (no mocked tools). Reproduces the exact step-C scenario:

    inspect_project (auto project recovery, no path)
    -> spawn_actor
    -> get_actor read-back
    -> save_level
    -> capture_unreal_viewport
    -> COMPLETE

Forbidden outcomes reported as FAIL: "uproject not found", PROJECT_CONTEXT_MISSING
without recovery, EXECUTION_STALLED.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.unreal import project_context as pc


def main():
    print("=== LIVE PROJECT CONTEXT CORE REGRESSION ===")

    # Worst case for "backend restart": no persisted project to lean on.
    print("\n[1] Simulating fresh backend (clearing durable context)...")
    pc.clear_active_context()
    assert not Path(pc.ACTIVE_CONTEXT_FILE).exists()

    print("[2] inspect_project() with NO path must auto-resolve via bridge...")
    from tools.unreal.project_manager import inspect_project
    r = inspect_project()
    problems = []
    if r.get("ok") is not True:
        problems.append(f"inspect_project ok=False: {r.get('code') or r.get('error')}")
    if "not found" in str(r.get("error") or "").lower():
        problems.append("inspect_project returned 'uproject not found'")
    print("    result ok=%s name=%s source=%s path=%s" % (
        r.get("ok"), r.get("name"), r.get("source_of_truth"), r.get("uproject_path"),
    ))
    with open(ROOT / "memory" / "active_project_context.json", "r", encoding="utf-8") as f:
        persisted = f.read()

    print("[3] Backend-restart reload: durable context file now exists and is valid")
    assert '"validity": "valid"' in persisted, "context not persisted as valid"
    assert "AvaLive" in persisted, "context did not record the live AvaLive project"
    print("    persisted context contains AvaLive + validity=valid")

    print("[4] Running the deterministic spawn-cube execution with NO project path...")
    from app import api
    # Avoid an extra LLM planning pass so the deterministic actor flow is precise;
    # normalize_execution_plan still builds inspect->spawn->get_actor->save->capture.
    api.create_execution_plan = lambda task: {
        "goal": task,
        "steps": ["Inspect", "Spawn", "Verify", "Save", "Capture"],
        "success_criteria": ["Real evidence confirms completion"],
        "risks": [],
    }
    task = (
        "Spawn a cube named PROJECT_CONTEXT_FINAL_TEST, save the level, "
        "verify it exists, and capture proof."
    )
    exec_state = api.new_execution(task)
    api.execution_state = exec_state

    # Idempotent re-runs: clear any leftover actors with the target label so
    # get_actor read-back is unambiguous regardless of prior runs.
    from tools.unreal.unreal_bridge import UnrealBridge
    bridge = UnrealBridge(timeout=8)
    for _ in range(4):
        res = (bridge.get_actor("PROJECT_CONTEXT_FINAL_TEST").get("result") or {})
        if res.get("ok") is True:
            bridge.delete_actor(res.get("name"))
        elif res.get("ok") is False and "Ambiguous" in str(res.get("error")):
            for m in res.get("matches", []):
                bridge.delete_actor(m)
        else:
            break

    result = api.run_execution_until_pause()

    steps = (exec_state.get("plan") or {}).get("steps", [])
    step_statuses = {s["step_id"]: s["status"] for s in steps}
    print("    terminal result state=%s verdict=%s stall_reason=%s" % (
        result.get("state"), result.get("terminal"), result.get("stall_reason"),
    ))
    print("    step statuses: %s" % step_statuses)

    # The deterministic engine reflects tool success as a completed step whose
    # preferred_tool is the tool that ran (trace is not populated on this path).
    ok_calls = {
        s["preferred_tool"]
        for s in steps
        if s.get("status") == "completed"
    }
    print("    successful tool calls (completed steps): %s" % sorted(ok_calls))

    verdict = result.get("terminal")
    if verdict != "PASS":
        problems.append("terminal verdict is not PASS: %s" % verdict)
    if result.get("stall_reason"):
        problems.append("EXECUTION_STALLED (reason=%s)" % result.get("stall_reason"))
    required = {"inspect_project", "unreal_ping", "spawn_actor", "get_actor", "save_level", "capture_unreal_viewport"}
    missing = required - ok_calls
    if missing:
        problems.append("missing successful tool calls: %s" % sorted(missing))

    print()
    if problems:
        print("LIVE PROJECT CONTEXT CORE FIX: FAIL")
        for p in problems:
            print("  -", p)
        return 1
    print("LIVE PROJECT CONTEXT CORE FIX: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())