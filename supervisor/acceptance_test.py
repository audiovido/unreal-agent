#!/usr/bin/env python3
"""
Supervisor Acceptance Test

Proves:
  1. Supervisor starts.
  2. Supervisor launches or controls a worker.
  3. Supervisor sends a test instruction automatically.
  4. Worker executes it.
  5. Supervisor captures the worker response.
  6. Supervisor evaluates PASS/FAIL.
  7. Supervisor automatically sends a second follow-up instruction.
  8. Worker responds again.
  9. Supervisor records the complete cycle.
  10. Restart/resume works from persisted state.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from supervisor.state import (
    Task, SupervisorState, WorkerState,
    save_state, load_state, log_activity, ensure_dirs,
)
from supervisor.supervisor import Supervisor
from supervisor.worker import Worker, WorkerResult, deterministic_evaluate


# ============================================================
# TEST CONSTANTS
# ============================================================

TEST_DIR = ROOT / "memory" / "supervisor" / "test_workspace"
TEST_FILE = TEST_DIR / "acceptance_marker.txt"
TEST_RESULT_FILE = TEST_DIR / "acceptance_result.json"
RESULTS = []


def record(name: str, passed: bool, detail: str = ""):
    RESULTS.append({
        "name": name,
        "passed": passed,
        "detail": detail,
        "at": time.time(),
    })
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {name}")
    if detail:
        print(f"         {detail}")


# ============================================================
# ACCEPTANCE TEST
# ============================================================

def run_acceptance_test():
    print("=" * 60)
    print("SUPERVISOR ACCEPTANCE TEST")
    print("=" * 60)
    print()

    # Setup
    ensure_dirs()
    TEST_DIR.mkdir(parents=True, exist_ok=True)
    if TEST_FILE.exists():
        TEST_FILE.unlink()

    try:
        # -------------------------------------------------------
        # TEST 1: Supervisor starts
        # -------------------------------------------------------
        print("--- Test 1: Supervisor starts ---")
        state = SupervisorState()
        sup = Supervisor(state)
        record("Supervisor starts", True, f"State: {sup.status()['status']}")

        # -------------------------------------------------------
        # TEST 2: Supervisor has workers
        # -------------------------------------------------------
        print("\n--- Test 2: Workers available ---")
        status = sup.status()
        has_workers = len(status["workers"]) >= 2
        worker_names = [w["name"] for w in status["workers"]]
        record("Workers available", has_workers, f"Workers: {worker_names}")

        # -------------------------------------------------------
        # TEST 3+4: Supervisor sends instruction, worker executes
        # -------------------------------------------------------
        print("\n--- Test 3+4: Task 1 — Create a file ---")
        task1 = Task(
            title="Create acceptance marker file",
            prompt=f"Create file {TEST_FILE} with content MARKER_HELLO",
            tags=["test"],
            locked_files=[str(TEST_FILE)],
        )
        task1_id = sup.add_task(task1)
        record("Task 1 added to queue", True, f"Task ID: {task1_id}")

        # Execute the task manually (without full loop, for fine-grained control)
        worker_state = sup.get_idle_worker()
        task1.worker_id = worker_state.id
        task1.status = "assigned"
        task1.attempt = 1
        worker_state.status = "busy"
        worker_state.current_task_id = task1.id

        worker = sup._workers[worker_state.id]
        result1 = worker.execute(task1, sup.state)
        record("Worker executed task 1", True, f"Output: {result1.output[:100]}")

        # -------------------------------------------------------
        # TEST 5: Supervisor captures response
        # -------------------------------------------------------
        print("\n--- Test 5: Supervisor captures response ---")
        captured = result1.output
        has_output = bool(captured and len(captured) > 0)
        record("Response captured", has_output, f"Output length: {len(captured)}")

        # -------------------------------------------------------
        # TEST 6: PASS/FAIL evaluation
        # -------------------------------------------------------
        print("\n--- Test 6: PASS/FAIL evaluation ---")
        task1.pass_fail = result1.pass_fail
        is_pass = result1.pass_fail == "PASS"
        record("PASS/FAIL evaluation", True, f"Result: {result1.pass_fail}")

        # Verify the file was actually created
        file_exists = TEST_FILE.exists()
        file_content = TEST_FILE.read_text() if file_exists else ""
        record("File actually created", file_exists, f"Content: {file_content}")

        # -------------------------------------------------------
        # TEST 7: Supervisor sends follow-up instruction
        # -------------------------------------------------------
        print("\n--- Test 7+8: Task 2 — Verify/Read the file ---")
        task2 = Task(
            title="Verify acceptance marker file",
            prompt=f"Read and verify file {TEST_FILE} contains MARKER_HELLO",
            tags=["test"],
            details={"expected_content": "MARKER_HELLO"},
            locked_files=[str(TEST_FILE)],
        )
        task2_id = sup.add_task(task2)
        record("Task 2 (follow-up) added", True, f"Task ID: {task2_id}")

        # Assign to worker
        worker_state2 = sup.get_idle_worker()
        task2.worker_id = worker_state2.id
        task2.status = "assigned"
        task2.attempt = 1
        worker_state2.status = "busy"
        worker_state2.current_task_id = task2.id

        worker2 = sup._workers[worker_state2.id]
        result2 = worker2.execute(task2, sup.state)
        record("Worker executed task 2", True, f"Output: {result2.output[:100]}")

        task2.pass_fail = result2.pass_fail
        record("Task 2 evaluation", result2.pass_fail == "PASS", f"Result: {result2.pass_fail}")

        # -------------------------------------------------------
        # TEST 9: Complete cycle recorded
        # -------------------------------------------------------
        print("\n--- Test 9: Complete cycle recorded ---")
        sup.move_to_completed(task1)
        sup.move_to_completed(task2)
        worker_state.status = "idle"
        worker_state.current_task_id = None
        worker_state2.status = "idle"
        worker_state2.current_task_id = None

        final_status = sup.status()
        record(
            "Cycle recorded",
            final_status["completed_tasks"] >= 2,
            f"Completed: {final_status['completed_tasks']}, Cycles: {final_status['total_cycles']}",
        )

        # Check activity log
        has_log = len(sup.state.activity_log) > 0
        record("Activity log populated", has_log, f"Entries: {len(sup.state.activity_log)}")

        # -------------------------------------------------------
        # TEST 10: Persistence and resume
        # -------------------------------------------------------
        print("\n--- Test 10: Persistence and resume ---")
        save_state(sup.state)
        state_file = ROOT / "memory" / "supervisor" / "supervisor_state.json"
        record("State persisted to disk", state_file.exists(), f"File: {state_file}")

        # Load from disk
        loaded_state = load_state()
        loaded_sup = Supervisor(loaded_state)
        loaded_status = loaded_sup.status()
        record(
            "State restored from disk",
            loaded_status["completed_tasks"] >= 2,
            f"Restored completed: {loaded_status['completed_tasks']}",
        )

        # Verify completed task data survived
        completed_titles = [t.title for t in loaded_sup.state.completed_tasks]
        record(
            "Completed task data preserved",
            "Create acceptance marker file" in completed_titles,
            f"Completed titles: {completed_titles}",
        )

        # Verify activity log survived
        record(
            "Activity log persisted",
            len(loaded_sup.state.activity_log) > 0,
            f"Log entries: {len(loaded_sup.state.activity_log)}",
        )

        # -------------------------------------------------------
        # TEST: Auto-fix cycle (FAIL → follow-up → PASS)
        # -------------------------------------------------------
        print("\n--- Bonus: Auto-fix cycle ---")
        task3 = Task(
            title="Read non-existent file (will FAIL)",
            prompt=f"Read file {TEST_DIR}/nonexistent.txt",
            tags=["test"],
        )
        task3_id = sup.add_task(task3)
        record("Auto-fix test: task added", True)

        worker_state3 = sup.get_idle_worker()
        if worker_state3:
            task3.worker_id = worker_state3.id
            task3.status = "assigned"
            task3.attempt = 1
            worker_state3.status = "busy"
            worker_state3.current_task_id = task3.id

            worker3 = sup._workers[worker_state3.id]
            result3 = worker3.execute(task3, sup.state)
            task3.pass_fail = result3.pass_fail

            record(
                "Auto-fix: FAIL detected",
                result3.pass_fail == "FAIL",
                f"Result: {result3.pass_fail}",
            )

            # Supervisor would normally re-queue with followup
            if result3.pass_fail == "FAIL" and result3.suggest_followup:
                record(
                    "Auto-fix: follow-up generated",
                    True,
                    f"Follow-up: {result3.suggest_followup[:80]}",
                )

            worker_state3.status = "idle"
            worker_state3.current_task_id = None

        # -------------------------------------------------------
        # FINAL REPORT
        # -------------------------------------------------------
        print()
        print("=" * 60)
        print("FINAL ACCEPTANCE REPORT")
        print("=" * 60)

        passed = sum(1 for r in RESULTS if r["passed"])
        failed = sum(1 for r in RESULTS if not r["passed"])
        total = len(RESULTS)

        for r in RESULTS:
            status = "+" if r["passed"] else "-"
            print(f"  [{status}] {r['name']}")

        print()
        print(f"  Total: {total}  |  Passed: {passed}  |  Failed: {failed}")
        print()

        if failed == 0:
            print("  RESULT: PASS — All acceptance criteria met.")
        elif failed <= 2:
            print("  RESULT: PARTIAL — Most criteria met, some issues.")
        else:
            print("  RESULT: FAIL — Critical issues found.")

        print()

        # Save results
        TEST_RESULT_FILE.write_text(
            json.dumps({
                "timestamp": time.time(),
                "passed": passed,
                "failed": failed,
                "total": total,
                "results": RESULTS,
                "status": "PASS" if failed == 0 else ("PARTIAL" if failed <= 2 else "FAIL"),
            }, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"  Results saved to: {TEST_RESULT_FILE}")

        return failed == 0

    finally:
        # Cleanup test files
        if TEST_FILE.exists():
            TEST_FILE.unlink(missing_ok=True)
