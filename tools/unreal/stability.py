"""Generic editor-stability guards for the Unreal Agent bridge.

PIE sessions regularly flick the game world on/off, and sibling automation can
leave the editor mid-transition. These helpers make any caller robust:

- ``wait_for_editor_world(bridge)`` — blocks until the editor (not PIE) world
  is present with level actors, then returns True.
- ``run_when_stable(bridge, code, ...)`` — returns a structured "busy" error
  instead of executing while PIE is up, with bounded retry.

The bridge protocol is duck-typed (just needs ``execute_python``), so the
retry/verdict logic is fully unit-testable with a fake bridge.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional

_STABLE_PROBE = """
import time as _t
def _ua_probe_stable():
    es = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    for _i in range({timeout_tenths}):
        try:
            _w = es.get_game_world()
            if _w is not None:
                return False
            _ew = es.get_editor_world()
            _acts = unreal.EditorLevelLibrary.get_all_level_actors()
            if _ew is not None and len(_acts) > 0:
                return True
        except Exception:
            pass
        _t.sleep(0.1)
    return False
__ua_stable__ = _ua_probe_stable()
__bridge_result__ = {{"ok": __ua_stable__}}
"""


def wait_for_editor_world(bridge: Any, timeout_seconds: float = 30.0) -> bool:
    """Probe until the editor world is stable (PIE off, level loaded)."""
    tenths = max(1, int(timeout_seconds * 10))
    r = bridge.execute_python(_STABLE_PROBE.format(timeout_tenths=tenths))
    result = r.get("result") if isinstance(r, dict) else None
    return bool(isinstance(result, dict) and result.get("ok"))


def run_when_stable(
    bridge: Any,
    code: str,
    *,
    timeout_seconds: float = 90.0,
    window_attempts: int = 30,
    window_delay: float = 6.0,
    stable_wait: float = 30.0,
    on_busy: Optional[Callable[[], None]] = None,
) -> Dict[str, Any]:
    """Run ``code`` only when the editor world is stable.

    Returns the code's result dict, or a dict with ``ok=False`` and
    ``error`` explaining why it never ran (PIE busy / bridge down).
    """
    last_error = "no attempt"
    for _ in range(window_attempts):
        ping = None
        if hasattr(bridge, "ping"):
            ping = bridge.ping()
            if not (isinstance(ping, dict) and ping.get("ok")):
                last_error = "bridge unavailable: " + str(ping.get("error"))[:80]
                time.sleep(window_delay)
                continue
        stable = False
        try:
            stable = wait_for_editor_world(bridge, timeout_seconds=stable_wait)
        except Exception as exc:  # pragma: no cover - transport failure
            last_error = "stability probe failed: " + str(exc)[:100]
            time.sleep(window_delay)
            continue
        if not stable:
            last_error = "editor world busy (PIE running or level loading)"
            if on_busy is not None:
                on_busy()
            time.sleep(window_delay)
            continue
        result = bridge.execute_python(code)
        out = result.get("result") if isinstance(result, dict) else result
        if isinstance(out, dict) and out.get("ok") is False and str(out.get("error", "")).startswith("editor world not stable"):
            last_error = "world flipped before execution"
            time.sleep(window_delay)
            continue
        return result
    return {"ok": False, "code": "WORLD_BUSY_TIMEOUT", "error": last_error}


def with_indent(code: str) -> str:
    """Indent code for embedding inside an if-block (used by stable runners)."""
    return "\n    ".join(code.strip().splitlines())