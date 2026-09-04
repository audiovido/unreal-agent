"""Test-suite isolation for durable Agent state.

1. Deterministic tests call api.new_execution(...), which persists the parent
   TaskGoal through core.task_goal.save_task_goal. Without isolation every
   pytest run overwrites the live Agent's memory/task_goal.json (observed: the
   AvaLive parent goal being replaced by a "cleanup probe" goal). Keep all
   writes in a per-test temp file instead.

2. Regression runs must NEVER accidentally reach a live Unreal bridge
   (127.0.0.1:6766). Real dispatches can open/save/mutate live editor maps.
   UnrealBridge._send is the single transport choke point for ALL live bridge
   I/O (ping, execute_python, spawn, capture, open/save level, ...). Under
   pytest it is blocked unless a test explicitly opts in with
   @pytest.mark.live_unreal. The blocker returns the same structured
   {"ok": False, "error": ...} shape the bridge already returns when it is
   unreachable, so existing bridge-down semantics are unchanged and no test
   can mutate a live editor by accident. Production bridge behavior is
   untouched (this fixture only exists under pytest).
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import task_goal

from tools.unreal.unreal_bridge import UnrealBridge


@pytest.fixture(autouse=True)
def _isolated_task_goal_file(tmp_path, monkeypatch):
    monkeypatch.setattr(task_goal, "TASK_GOAL_FILE", tmp_path / "task_goal.json")


# Marker used by explicit live-Unreal tests (kept separate and opt-in).
# Registered in pytest.ini so it is never reported as an unknown marker.
LIVE_UNREAL_MARKER = "live_unreal"
BLOCKED_ERROR = (
    "REGRESSION_ISOLATION: live Unreal bridge access blocked while pytest is "
    "running (would mutate the real editor). Opt in explicitly with "
    "@pytest.mark.live_unreal on the test."
)


def _blocked_send(self, payload):
    """Transport guard: structured refusal identical in shape to the error
    UnrealBridge._send already returns when the bridge is unreachable."""
    return {"ok": False, "error": BLOCKED_ERROR}


@pytest.fixture(autouse=True)
def _block_live_unreal_bridge(request, monkeypatch):
    """Hermetic regression guard: no unmarked test can reach a live bridge."""
    if request.node.get_closest_marker(LIVE_UNREAL_MARKER):
        return
    monkeypatch.setattr(UnrealBridge, "_send", _blocked_send)


MODEL_BLOCKED_ERROR = (
    "REGRESSION_ISOLATION: live Ollama model call blocked while pytest is "
    "running (would load a 20GB model / block on a wedged server). Opt in "
    "explicitly with @pytest.mark.live_unreal on the test or mock the model "
    "call yourself."
)


@pytest.fixture(autouse=True)
def _block_live_model_calls(request, monkeypatch):
    """Hermetic regression guard: no unmarked test may make a real Ollama
    model call.

    core.orchestrator.call_model is the single transport choke point for LLM
    I/O (requests.post to Ollama with a 600s socket timeout). Without this
    guard, any test that routes through planning (e.g. api.new_execution) hits
    the real server: it can load the 20GB coder model (multi-minute wedge) or
    block for 10 minutes on a wedged Ollama. Planning callers already carry a
    real fallback plan on exception, so a fast refusal keeps them functional
    and bounded. Production behavior is untouched (this fixture only exists
    under pytest)."""
    from core import orchestrator

    if request.node.get_closest_marker(LIVE_UNREAL_MARKER):
        return

    def _blocked_model(*args, **kwargs):
        raise RuntimeError(MODEL_BLOCKED_ERROR)

    monkeypatch.setattr(orchestrator, "call_model", _blocked_model)