"""Test-suite isolation for durable Agent state.

Several deterministic tests call api.new_execution(...), which persists the
parent TaskGoal through core.task_goal.save_task_goal. Without isolation every
pytest run overwrites the live Agent's memory/task_goal.json (observed: the
AvaLive parent goal being replaced by a "cleanup probe" goal). Keep all writes
in a per-test temp file instead.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import task_goal


@pytest.fixture(autouse=True)
def _isolated_task_goal_file(tmp_path, monkeypatch):
    monkeypatch.setattr(task_goal, "TASK_GOAL_FILE", tmp_path / "task_goal.json")