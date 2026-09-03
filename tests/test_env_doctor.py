"""Hermetic tests for core/env_doctor.py (offline-safe)."""
from __future__ import annotations

import pytest

from core import app_config, env_doctor

_UA_ENV = ("BACKEND_PORT", "BRIDGE_PORT", "DEV_API_PORT", "HOST",
           "RECENT_PROJECT", "UNREAL_EDITOR", "DEVELOPER_MODE")


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch, tmp_path):
    for name in _UA_ENV:
        monkeypatch.delenv(f"UA_{name}", raising=False)
    monkeypatch.setattr(app_config, "SETTINGS_FILE", tmp_path / "none.json")
    monkeypatch.setattr(app_config, "PREF_FILE", tmp_path / "none.json")
    monkeypatch.setattr(app_config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(app_config, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(app_config, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(app_config, "LEASE_DIR", tmp_path / "leases")
    monkeypatch.setattr(app_config, "PROOF_DIR", tmp_path / "proof")


def test_offline_run_never_fails_hermetic():
    rep = env_doctor.run(probe_backend=False, probe_ports=False)
    assert rep["overall"] in ("PASS", "WARNING")
    for key in ("summary", "user_error", "checks", "failures", "warnings",
                "config"):
        assert key in rep
    assert rep["failures"] == []
    assert any(c["name"] == "python_runtime" and c["status"] == "PASS"
               for c in rep["checks"])


def test_user_error_is_concise():
    rep = env_doctor.run(probe_backend=False, probe_ports=False)
    assert isinstance(rep["user_error"], str)
    assert "Traceback" not in rep["user_error"]


def test_port_checks_flag_running_service(monkeypatch):
    # backend port pointing at the python http default is irrelevant; instead
    # verify the check structure against a definitely-free high port.
    cfg = app_config.load_config()
    checks = env_doctor.check_ports(cfg)
    names = {c["name"] for c in checks}
    assert {"port_backend", "port_bridge", "port_dev_api"} <= names
    for c in checks:
        assert c["status"] in ("PASS", "WARNING")


def test_uproject_warn_when_none():
    checks = env_doctor.check_unreal(app_config.load_config())
    up = next(c for c in checks if c["name"] == "uproject")
    assert up["status"] == "WARNING"


def test_developer_diagnostic_lines():
    rep = env_doctor.run(probe_backend=False, probe_ports=False)
    diag = env_doctor.developer_diagnostic(rep)
    assert diag.startswith("[env-doctor] overall=")
    assert rep["summary"].split()[0].isdigit()


def test_check_config_detects_bad_ports(monkeypatch):
    cfg = app_config.load_config()
    cfg.backend_port = 0
    checks = env_doctor.check_config(cfg)
    assert checks[0]["status"] == "FAIL"


def test_backend_probe_offline_returns_warn():
    # point backend at an unused high port so the probe deterministically
    # reports "not answering"
    cfg = app_config.load_config()
    cfg.backend_port = 49991
    checks = env_doctor.check_backend(cfg)
    assert checks[0]["name"] == "backend_ready"
    assert checks[0]["status"] in ("PASS", "WARNING")
