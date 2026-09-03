"""Hermetic tests for core/service_lifecycle.py.

Spawns only tiny local python http servers on ephemeral ports; never
touches Unreal or the real product backend.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from core import app_config, service_lifecycle as svc


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch, tmp_path):
    monkeypatch.setattr(svc, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(svc, "LOG_DIR", tmp_path / "logs")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _spawn_http_server(port: int, tmp: Path) -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=str(tmp), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 8
    while time.time() < deadline:
        if svc.port_in_use("127.0.0.1", port):
            return proc
        time.sleep(0.1)
    proc.terminate()
    raise RuntimeError("http server did not start")


# ---------------------------------------------------------------------------
# pid helpers
# ---------------------------------------------------------------------------

def test_pid_file_roundtrip_and_clear(tmp_path):
    svc.write_pid_file("svc-x", 12345, port=9999)
    rec = svc.read_pid_file("svc-x")
    assert rec and rec["pid"] == 12345 and rec["port"] == 9999
    svc.clear_pid_file("svc-x")
    assert svc.read_pid_file("svc-x") is None


def test_pid_alive_dead_pid():
    assert svc.pid_alive(None) is False
    assert svc.pid_alive(0) is False
    assert svc.pid_alive(2 ** 31 - 1) is False  # impossibly high -> dead


def _wait_port_free(port: int, timeout: float = 6.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not svc.port_in_use("127.0.0.1", port):
            return True
        time.sleep(0.1)
    return False


def test_port_in_use_and_http_ready(tmp_path):
    port = _free_port()
    proc = _spawn_http_server(port, tmp_path)
    try:
        assert svc.port_in_use("127.0.0.1", port) is True
        assert svc.http_ready(f"http://127.0.0.1:{port}/") is True
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    assert _wait_port_free(port) is True
    assert svc.port_in_use("127.0.0.1", port) is False


# ---------------------------------------------------------------------------
# stop / stale recovery
# ---------------------------------------------------------------------------

def test_stop_with_stale_pid_file():
    svc.write_pid_file("svc-stale", 2 ** 31 - 1, port=_free_port())
    res = svc.stop_service("svc-stale", "127.0.0.1", _free_port())
    assert res["ok"] is True
    assert svc.read_pid_file("svc-stale") is None


def test_service_status_recovers_stale(tmp_path):
    port = _free_port()
    svc.write_pid_file("svc-stale2", 2 ** 31 - 1, port=port)
    st = svc.service_status("svc-stale2", "127.0.0.1", port)
    assert st["state"] == "STALE"
    assert svc.read_pid_file("svc-stale2") is None
    st2 = svc.service_status("svc-stale2", "127.0.0.1", port)
    assert st2["state"] == "STOPPED"


def test_stop_running_server(tmp_path):
    port = _free_port()
    proc = _spawn_http_server(port, tmp_path)
    try:
        svc.write_pid_file("svc-live", proc.pid, port=port)
        res = svc.stop_service("svc-live", "127.0.0.1", port, grace_s=5)
        assert res["ok"] is True
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=10)


# ---------------------------------------------------------------------------
# duplicate protection
# ---------------------------------------------------------------------------

def test_start_refuses_duplicate_on_port(tmp_path):
    port = _free_port()
    proc = _spawn_http_server(port, tmp_path)
    try:
        res = svc.start_service("dup-test", "127.0.0.1", port,
                                "not.a.real:app",
                                ready_timeout_s=2)
        assert res["ok"] is False
        assert res["duplicate"] is True
        assert "already in use" in res["error"]
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_start_refuses_when_pid_file_alive(tmp_path):
    # a live pid in the pid file means we consider the service already up
    import os
    me = os.getpid()
    svc.write_pid_file("dup-pid", me, port=_free_port())
    res = svc.start_service("dup-pid", "127.0.0.1", _free_port(),
                            "not.a.real:app", ready_timeout_s=1)
    assert res["duplicate"] is True and res.get("pid") == me
    svc.clear_pid_file("dup-pid")


# ---------------------------------------------------------------------------
# bounded restart (never infinite)
# ---------------------------------------------------------------------------

def test_ensure_running_is_bounded(tmp_path):
    port = _free_port()
    res = svc.ensure_running("bounded", "127.0.0.1", port,
                             "not.a.real.module:app",
                             max_attempts=2, backoff_s=0.1,
                             log_suffix="bounded-test")
    assert res["ok"] is False
    assert res["attempts"] == 2
    assert len(res["history"]) == 2
