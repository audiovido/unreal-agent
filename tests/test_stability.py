"""Deterministic tests for tools.unreal.stability using a fake bridge."""
import time

from tools.unreal.stability import run_when_stable, wait_for_editor_world


class FakeBridge:
    def __init__(self, stable_after=0, execute_result=None):
        self.calls = []
        self.stable_after = stable_after
        self.probe_count = 0
        self.execute_result = execute_result or {"ok": True, "result": {"ok": True, "ran": True}}

    def ping(self):
        self.calls.append("ping")
        return {"ok": True, "message": "fake"}

    def execute_python(self, code):
        self.calls.append("exec")
        self.probe_count += 1
        if "__ua_stable__" in code:
            return {"ok": True, "result": {"ok": self.probe_count > self.stable_after}}
        return self.execute_result


def test_wait_for_editor_world_true_immediately():
    b = FakeBridge(stable_after=0)
    assert wait_for_editor_world(b, timeout_seconds=2) is True


def test_wait_for_editor_world_false_when_never_stable():
    b = FakeBridge(stable_after=999)
    assert wait_for_editor_world(b, timeout_seconds=0.5) is False


def test_run_when_stable_returns_result():
    b = FakeBridge(stable_after=0)
    out = run_when_stable(b, "x = 1", window_attempts=3, window_delay=0.01, stable_wait=0.5)
    assert out.get("result", {}).get("ran") is True


def test_run_when_stable_waits_for_stable_window():
    b = FakeBridge(stable_after=2)
    out = run_when_stable(b, "x = 1", window_attempts=10, window_delay=0.01, stable_wait=0.5)
    assert out.get("result", {}).get("ran") is True
    assert b.probe_count >= 2


def test_run_when_stable_gives_up_with_struct_error():
    b = FakeBridge(stable_after=9999)
    out = run_when_stable(b, "x = 1", window_attempts=3, window_delay=0.01, stable_wait=0.3)
    assert out.get("ok") is False
    assert "WORLD_BUSY_TIMEOUT" in str(out.get("code"))


def test_bridge_down_reports_unavailable():
    class DownBridge(FakeBridge):
        def ping(self):
            return {"ok": False, "error": "ConnectionRefusedError"}

    b = DownBridge()
    out = run_when_stable(b, "x = 1", window_attempts=2, window_delay=0.01)
    assert out.get("ok") is False
    assert "bridge unavailable" in out.get("error", "")


def test_with_indent_preserves_executable_semantics():
    from tools.unreal.stability import with_indent

    code = "a = 1\nb = a + 1"
    indented = with_indent(code)
    ns = {}
    exec("if True:\n    " + indented, ns)
    assert ns["b"] == 2


def test_on_busy_callback_invoked():
    events = []
    b = FakeBridge(stable_after=999)
    run_when_stable(
        b, "x = 1",
        window_attempts=2, window_delay=0.01, stable_wait=0.2,
        on_busy=lambda: events.append("busy"),
    )
    assert "busy" in events