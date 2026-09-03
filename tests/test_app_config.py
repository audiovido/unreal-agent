"""Hermetic tests for core/app_config.py (no editor, no live services)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import app_config

_UA_ENV = ("BACKEND_PORT", "BRIDGE_PORT", "DEV_API_PORT", "HOST",
           "RECENT_PROJECT", "UNREAL_EDITOR", "DEVELOPER_MODE")


@pytest.fixture(autouse=True)
def _scrub_env(monkeypatch):
    for name in _UA_ENV:
        monkeypatch.delenv(f"UA_{name}", raising=False)


def test_defaults_when_nothing_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(app_config, "SETTINGS_FILE", tmp_path / "none.json")
    monkeypatch.setattr(app_config, "PREF_FILE", tmp_path / "none.json")
    cfg = app_config.load_config()
    assert cfg.backend_host == "127.0.0.1"
    assert cfg.backend_port == 8799
    assert cfg.bridge_port == 6766
    assert cfg.dev_api_port == 8765
    assert cfg.developer_mode is False
    assert cfg.backend_url == "http://127.0.0.1:8799"


def test_settings_file_with_bom_is_read(monkeypatch, tmp_path):
    settings = tmp_path / "settings.json"
    # dev-console settings are saved as utf-8-sig; loader must tolerate the BOM
    settings.write_bytes(
        "\ufeff".encode("utf-8") + json.dumps(
            {"backend_port": 8123, "unreal": {"editor_exe": "C:/UE/Editor.exe"}}
        ).encode("utf-8"))
    monkeypatch.setattr(app_config, "SETTINGS_FILE", settings)
    monkeypatch.setattr(app_config, "PREF_FILE", tmp_path / "none.json")
    cfg = app_config.load_config()
    assert cfg.backend_port == 8123
    assert cfg.unreal_editor_exe == "C:/UE/Editor.exe"


def test_env_overrides_defaults(monkeypatch, tmp_path):
    monkeypatch.setattr(app_config, "SETTINGS_FILE", tmp_path / "none.json")
    monkeypatch.setattr(app_config, "PREF_FILE", tmp_path / "none.json")
    monkeypatch.setenv("UA_BACKEND_PORT", "9123")
    monkeypatch.setenv("UA_DEVELOPER_MODE", "1")
    cfg = app_config.load_config()
    assert cfg.backend_port == 9123
    assert cfg.developer_mode is True


def test_set_pref_persists_and_reloads(monkeypatch, tmp_path):
    pref = tmp_path / "prefs.json"
    monkeypatch.setattr(app_config, "PREF_FILE", pref)
    r = app_config.set_pref("developer_mode", True, overlay=pref)
    assert r["ok"] is True
    cfg = app_config.load_config(overlay=pref)
    assert cfg.developer_mode is True


def test_set_pref_allowlist(tmp_path):
    with pytest.raises(ValueError):
        app_config.set_pref("not_a_real_key", 1, overlay=tmp_path / "x.json")


def test_validate_uproject(tmp_path):
    good = tmp_path / "Show.uproject"
    good.write_text(json.dumps({"FileVersion": 3,
                                "EngineAssociation": "5.4"}), encoding="utf-8")
    res = app_config.validate_uproject(str(good))
    assert res["ok"] is True
    assert res["name"] == 3
    assert app_config.validate_uproject(str(tmp_path / "missing.uproject"))[
        "ok"] is False
    bad = tmp_path / "bad.uproject"
    bad.write_text("{not json", encoding="utf-8")
    assert app_config.validate_uproject(str(bad))["ok"] is False


def test_disk_free_returns_number():
    assert isinstance(app_config.disk_free_bytes(), int)


def test_detect_unreal_builds_returns_list():
    builds = app_config.detect_unreal_builds()
    assert isinstance(builds, list)
    for b in builds:
        assert "label" in b and "editor_exe" in b
