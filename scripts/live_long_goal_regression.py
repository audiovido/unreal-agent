"""Live synthetic long-goal regression for goal preservation and false-complete
protection. Operates only on temporary named actors in the currently open
Unreal project and removes prior copies before running.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import api
from core import task_goal
from tools.unreal.unreal_bridge import UnrealBridge


def main():
    task = (
        "Create a test scene with a cube named GOAL_TEST, add a light, save the "
        "level, verify both exist, capture a screenshot."
    )
    print("=== LIVE LONG-GOAL REGRESSION ===")
    bridge = UnrealBridge(timeout=60)

    # Idempotent cleanup of only the synthetic names.
    for label in ("GOAL_TEST", "GOAL_TEST_LIGHT"):
        for _ in range(4):
            result = bridge.get_actor(label).get("result") or {}
            if result.get("ok"):
                bridge.delete_actor(result.get("name"))
            elif "Ambiguous" in str(result.get("error")):
                for name in result.get("matches", []):
                    bridge.delete_actor(name)
            else:
                break

    original = api.create_execution_plan
    api.create_execution_plan = lambda _: {"goal": task, "steps": [], "success_criteria": []}
    try:
        state = api.new_execution(task)
    finally:
        api.create_execution_plan = original

    # Prove the parent goal is present before execution, not inferred afterward.
    goal = state.get("task_goal") or {}
    print("parent goal persisted before tools:", bool(goal.get("original_user_request")))
    print("pending criteria before tools:", goal.get("pending_criteria"))
    api.execution_state = state
    result = api.run_execution_until_pause()

    steps = state.get("plan", {}).get("steps", [])
    sequence = [s.get("preferred_tool") for s in steps if s.get("status") == "completed"]
    print("completed sequence:", sequence)
    print("step statuses:", [(s.get("step_id"), s.get("preferred_tool"), s.get("status")) for s in steps])
    print("terminal:", result.get("terminal"), "state:", result.get("state"), "stall:", result.get("stall_reason"))
    print("pending criteria after tools:", (state.get("task_goal") or {}).get("pending_criteria"))

    identity = bridge.get_project_identity().get("result") or {}
    cube = bridge.get_actor("GOAL_TEST").get("result") or {}
    light = bridge.get_actor("GOAL_TEST_LIGHT").get("result") or {}
    print("project:", identity.get("project_name"), identity.get("project_path"))
    print("cube:", cube)
    print("light:", light)

    required = ["inspect_project", "unreal_ping", "spawn_actor", "spawn_actor", "save_level", "get_actor", "get_actor", "capture_unreal_viewport"]
    problems = []
    if result.get("terminal") != "PASS":
        problems.append("not COMPLETE/PASS")
    if result.get("stall_reason"):
        problems.append("EXECUTION_STALLED")
    if sequence != required:
        problems.append(f"sequence mismatch: expected {required}")
    if identity.get("project_name") != "AvaLive":
        problems.append("wrong active project")
    if cube.get("ok") is not True or light.get("ok") is not True:
        problems.append("independent actor read-back failed")
    if (state.get("task_goal") or {}).get("pending_criteria"):
        problems.append("parent goal still has pending criteria")
    if not goal.get("original_user_request"):
        problems.append("original goal was lost")

    if problems:
        print("LIVE LONG-GOAL REGRESSION: FAIL")
        for problem in problems:
            print(" -", problem)
        return 1
    print("LIVE LONG-GOAL REGRESSION: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
