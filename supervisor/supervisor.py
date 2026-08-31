"""
Main Supervisor loop.

Cycle per task:
  1. READ CURRENT STATE
  2. ASSIGN TASK to an idle worker
  3. WORKER EXECUTES
  4. BUILD / RUN / TEST (handled inside worker)
  5. READ RESULT
  6. PASS or FAIL
  7. AUTO-FIX if FAIL (send corrective follow-up)
  8. NEXT TASK if PASS
  9. Record cycle in persisted state
"""

from __future__ import annotations

import json
import time
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from supervisor.state import (
    Task, WorkerState, SupervisorState,
    save_state, load_state, log_activity,
    release_all_locks, create_checkpoint,
    ensure_dirs, MAX_RETRIES,
)
from supervisor.worker import Worker, WorkerResult, create_default_workers


# ============================================================
# SUPERVISOR
# ============================================================

class Supervisor:
    """
    Orchestrates parallel task execution across two workers.

    Usage:
        sup = Supervisor()
        sup.add_task(Task(title="Test 1", prompt="...", tags=["test"]))
        sup.run()
    """

    def __init__(self, state: SupervisorState | None = None):
        ensure_dirs()
        release_all_locks()

        self.state = state or load_state()
        self._workers: dict[str, Worker] = {}
        self._init_workers()

    def _init_workers(self):
        """Initialize or restore workers."""
        if not self.state.workers:
            self.state.workers = create_default_workers()
            save_state(self.state)

        for ws in self.state.workers:
            self._workers[ws.id] = Worker(ws)

    # --------------------------------------------------------
    # TASK MANAGEMENT
    # --------------------------------------------------------

    def add_task(self, task: Task) -> str:
        """Add a task to the queue. Returns task ID."""
        self.state.tasks.append(task)
        log_activity(self.state, "task_added", f"Task added: {task.title}", task_id=task.id)
        save_state(self.state)
        return task.id

    def add_tasks(self, tasks: list[Task]) -> list[str]:
        """Add multiple tasks. Returns task IDs."""
        ids = []
        for t in tasks:
            ids.append(self.add_task(t))
        return ids

    def get_next_task(self) -> Task | None:
        """Get the next queued task."""
        for t in self.state.tasks:
            if t.status == "queued":
                return t
        return None

    def get_idle_worker(self) -> WorkerState | None:
        """Find an idle worker."""
        for w in self.state.workers:
            if w.status == "idle":
                return w
        return None

    def move_to_completed(self, task: Task):
        """Move a finished task from active queue to completed."""
        self.state.tasks = [t for t in self.state.tasks if t.id != task.id]
        self.state.completed_tasks.append(task)

    # --------------------------------------------------------
    # MAIN LOOP
    # --------------------------------------------------------

    def run(self, max_cycles: int = 100, tick_interval: float = 1.0, on_result: Callable | None = None):
        """
        Run the supervisor loop.

        Args:
            max_cycles: maximum iterations before stopping
            tick_interval: seconds between checks
            on_result: optional callback(task, result) after each execution
        """
        self.state.status = "running"
        self.state.started_at = self.state.started_at or time.time()
        save_state(self.state)

        log_activity(self.state, "supervisor_started", "Supervisor loop started")
        print(f"[SUPERVISOR] Started. {len(self.state.tasks)} tasks in queue.")

        try:
            for cycle in range(max_cycles):
                self.state.total_cycles = cycle + 1
                self.state.last_tick = time.time()

                # Check if all tasks are done
                queued = [t for t in self.state.tasks if t.status in ("queued", "assigned", "running")]
                if not queued:
                    print(f"[SUPERVISOR] All tasks complete after {cycle + 1} cycles.")
                    log_activity(self.state, "supervisor_complete", "All tasks completed")
                    break

                # Try to assign and execute
                executed_any = self._tick()

                if not executed_any:
                    time.sleep(tick_interval)

                save_state(self.state)

        except KeyboardInterrupt:
            print("\n[SUPERVISOR] Interrupted. State saved.")
            log_activity(self.state, "supervisor_interrupted", "Keyboard interrupt")
        except Exception as exc:
            print(f"\n[SUPERVISOR] Error: {exc}")
            log_activity(self.state, "supervisor_error", f"Error: {exc}")
        finally:
            self.state.status = "idle"
            save_state(self.state)

    def _tick(self) -> bool:
        """One supervisor tick. Returns True if any task was executed."""
        executed_any = False

        # Find idle worker and next task
        worker_state = self.get_idle_worker()
        task = self.get_next_task()

        if worker_state is None or task is None:
            return False

        # Assign task to worker
        task.worker_id = worker_state.id
        task.status = "assigned"
        task.assigned_at = time.time()
        worker_state.status = "busy"
        worker_state.current_task_id = task.id

        print(f"\n[SUPERVISOR] Assigning '{task.title}' to {worker_state.name}")
        log_activity(self.state, "task_assigned",
                     f"Assigned '{task.title}' to {worker_state.name}",
                     task_id=task.id, worker_id=worker_state.id)

        # Checkpoint before execution
        if task.locked_files:
            cp_id = create_checkpoint(task.id, task.locked_files)
            log_activity(self.state, "checkpoint", f"Checkpoint created: {cp_id}", task_id=task.id)

        # Execute
        task.status = "running"
        task.started_at = time.time()
        task.attempt += 1
        save_state(self.state)

        worker = self._workers[worker_state.id]
        result = worker.execute(task, self.state)

        # Process result
        task.pass_fail = result.pass_fail
        task.last_output = result.output
        task.finished_at = time.time()

        if result.error:
            task.error = result.error

        if result.pass_fail == "PASS":
            task.status = "passed"
            worker_state.tasks_completed += 1
            print(f"[SUPERVISOR] Task PASSED: {task.title}")
            log_activity(self.state, "task_passed",
                         f"Task PASSED: {task.title} (attempt {task.attempt})",
                         task_id=task.id)

            self.move_to_completed(task)

        elif result.pass_fail == "FAIL":
            if task.attempt >= task.max_attempts:
                task.status = "blocked"
                task.blocked_reason = f"Max retries ({task.max_attempts}) exceeded"
                print(f"[SUPERVISOR] Task BLOCKED: {task.title} — max retries exceeded")
                log_activity(self.state, "task_blocked",
                             f"Task BLOCKED: {task.title} — max retries",
                             task_id=task.id)
                self.move_to_completed(task)
            else:
                task.status = "queued"  # re-queue for retry
                task.followup_prompt = result.suggest_followup
                # Update the prompt for the retry
                if result.suggest_followup:
                    task.prompt = result.suggest_followup
                worker_state.tasks_failed += 1
                print(f"[SUPERVISOR] Task FAILED (attempt {task.attempt}): {task.title}")
                print(f"[SUPERVISOR] Follow-up: {result.suggest_followup}")
                log_activity(self.state, "task_failed",
                             f"Task FAILED: {task.title} (attempt {task.attempt})",
                             task_id=task.id,
                             followup=result.suggest_followup)

        elif result.pass_fail == "ERROR":
            task.status = "blocked"
            task.blocked_reason = result.error
            print(f"[SUPERVISOR] Task ERROR: {task.title} — {result.error}")
            log_activity(self.state, "task_error",
                         f"Task ERROR: {task.title} — {result.error}",
                         task_id=task.id)
            self.move_to_completed(task)

        elif result.pass_fail == "BLOCKED":
            task.status = "blocked"
            task.blocked_reason = result.error
            self.move_to_completed(task)

        # Reset worker
        worker_state.status = "idle"
        worker_state.current_task_id = None
        worker_state.last_heartbeat = time.time()
        worker_state.last_output = result.output[:500]

        if on_result := getattr(self, '_on_result', None):
            on_result(task, result)

        save_state(self.state)
        executed_any = True
        return executed_any

    # --------------------------------------------------------
    # HTTP API MODE (for integration with existing FastAPI)
    # --------------------------------------------------------

    def execute_task_via_api(self, task: Task, api_url: str = "http://127.0.0.1:8765") -> WorkerResult:
        """Execute a task via the existing FastAPI backend HTTP API."""
        import requests
        start = time.time()
        result = WorkerResult(task_id=task.id, worker_id="api_worker")

        try:
            resp = requests.post(
                f"{api_url}/api/chat",
                json={"message": task.prompt},
                timeout=300,
            )
            resp.raise_for_status()
            data = resp.json()
            result.output = json.dumps(data, default=str, ensure_ascii=False)
            result.execution_time = time.time() - start

            # Simple evaluation
            if "error" in result.output.lower():
                result.pass_fail = "FAIL"
                result.suggest_followup = "Fix the error and retry."
            else:
                result.pass_fail = "PASS"

        except Exception as exc:
            result.pass_fail = "ERROR"
            result.error = f"{type(exc).__name__}: {exc}"
            result.execution_time = time.time() - start

        return result

    # --------------------------------------------------------
    # STATUS
    # --------------------------------------------------------

    def status(self) -> dict:
        """Return current supervisor status."""
        return {
            "status": self.state.status,
            "workers": [
                {
                    "id": w.id,
                    "name": w.name,
                    "role": w.role,
                    "status": w.status,
                    "current_task": w.current_task_id,
                    "completed": w.tasks_completed,
                    "failed": w.tasks_failed,
                }
                for w in self.state.workers
            ],
            "queued_tasks": len([t for t in self.state.tasks if t.status == "queued"]),
            "running_tasks": len([t for t in self.state.tasks if t.status == "running"]),
            "completed_tasks": len(self.state.completed_tasks),
            "total_cycles": self.state.total_cycles,
            "started_at": self.state.started_at,
        }
