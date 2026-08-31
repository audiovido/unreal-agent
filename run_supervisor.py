#!/usr/bin/env python3
"""
Supervisor CLI — run, status, resume, and manage the supervisor.

Usage:
    python run_supervisor.py run          # Run supervisor with queued tasks
    python run_supervisor.py status       # Show current status
    python run_supervisor.py resume       # Resume from persisted state
    python run_supervisor.py test         # Run acceptance test
    python run_supervisor.py reset        # Reset supervisor state
    python run_supervisor.py add "task"   # Add a task to the queue
"""

from __future__ import annotations

import sys
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from supervisor.state import Task, SupervisorState, save_state, load_state, ensure_dirs
from supervisor.supervisor import Supervisor


def cmd_run():
    """Run the supervisor with all queued tasks."""
    sup = Supervisor()
    status = sup.status()
    print(f"Queued tasks: {status['queued_tasks']}")
    print(f"Workers: {len(status['workers'])}")

    if status["queued_tasks"] == 0:
        print("No tasks in queue. Add tasks first.")
        return

    sup.run(max_cycles=200, tick_interval=0.5)
    print("\n=== FINAL STATUS ===")
    print(json.dumps(sup.status(), indent=2, default=str))


def cmd_status():
    """Show supervisor status."""
    state = load_state()
    sup = Supervisor(state)
    print(json.dumps(sup.status(), indent=2, default=str))

    if state.completed_tasks:
        print(f"\nCompleted tasks ({len(state.completed_tasks)}):")
        for t in state.completed_tasks:
            print(f"  [{t.pass_fail or '?'}] {t.title} (attempt {t.attempt})")

    if state.activity_log:
        print(f"\nRecent activity ({len(state.activity_log)} entries):")
        for entry in state.activity_log[-10:]:
            print(f"  {entry['kind']}: {entry['text']}")


def cmd_resume():
    """Resume from persisted state."""
    state = load_state()
    if not state.tasks:
        print("No tasks to resume.")
        return

    sup = Supervisor(state)
    print(f"Resuming. {len(state.tasks)} tasks remaining.")
    sup.run(max_cycles=200, tick_interval=0.5)


def cmd_test():
    """Run the acceptance test."""
    from supervisor.acceptance_test import run_acceptance_test
    run_acceptance_test()


def cmd_reset():
    """Reset supervisor state."""
    from supervisor.state import STATE_FILE
    if STATE_FILE.exists():
        STATE_FILE.unlink()
    print("Supervisor state reset.")


def cmd_add(prompt: str, title: str = "", tags: str = ""):
    """Add a task to the queue."""
    sup = Supervisor()
    task = Task(
        title=title or prompt[:60],
        prompt=prompt,
        tags=[t.strip() for t in tags.split(",") if t.strip()],
    )
    task_id = sup.add_task(task)
    print(f"Task added: {task_id}")
    print(json.dumps(sup.status(), indent=2, default=str))


def main():
    ensure_dirs()

    if len(sys.argv) < 2:
        print(__doc__)
        return

    command = sys.argv[1].lower()

    if command == "run":
        cmd_run()
    elif command == "status":
        cmd_status()
    elif command == "resume":
        cmd_resume()
    elif command == "test":
        cmd_test()
    elif command == "reset":
        cmd_reset()
    elif command == "add":
        if len(sys.argv) < 3:
            print("Usage: run_supervisor.py add \"task prompt\" [\"title\"] [\"tag1,tag2\"]")
            return
        prompt = sys.argv[2]
        title = sys.argv[3] if len(sys.argv) > 3 else ""
        tags = sys.argv[4] if len(sys.argv) > 4 else ""
        cmd_add(prompt, title, tags)
    else:
        print(f"Unknown command: {command}")
        print(__doc__)


if __name__ == "__main__":
    main()
