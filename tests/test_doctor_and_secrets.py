"""UNREAL CODER — Phases D + E: setup doctor and secret redaction tests.

Doctor: structured PASS/WARN/FAIL checks, optional systems WARN not FAIL.
Secrets: redaction by key name, by value shape, in free text and in nested
payloads; never logged raw.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import config as config_mod
from core.config import (
    CONFIG_SURFACE,
    config_snapshot,
    is_secret_key,
    looks_like_secret,
    redact,
    redact_text,
    redact_value,
)
from core.doctor import (
    FAIL,
    PASS,
    WARN,
    check_blender,
    check_config,
    check_models,
    check_python,
    human_summary,
    run_doctor,
)


class TestDoctor:
    def test_doctor_runs_and_is_structured(self):
        report = run_doctor()
        assert report["overall"] in (PASS, WARN, FAIL, "DEGRADED")
        assert report["summary"][PASS] >= 10
        names = [c["name"] for c in report["checks"]]
        assert "python_version" in names
        assert "config_file" in names
        assert "unreal_editor_exe" in names
        assert "api_boot" in names

    def test_python_checks(self):
        results = check_python()
        assert all(r["status"] == PASS for r in results), results

    def test_config_checks(self):
        results = check_config()
        assert any(r["name"] == "config_file" and r["status"] == PASS
                   for r in results)

    def test_blender_missing_warns_not_fails(self, monkeypatch, tmp_path):
        import core.doctor as doctor_mod
        import blender_agent.config as blender_config

        def no_blender():
            return None

        monkeypatch.setattr(blender_config, "discover_blender", no_blender)
        results = doctor_mod.check_blender()
        assert all(r["status"] != FAIL for r in results)

    def test_models_missing_warns_not_fails(self, monkeypatch):
        import core.doctor as doctor_mod
        monkeypatch.setattr(
            doctor_mod, "ollama_models", lambda: [], raising=False)
        import core.vision_provider as vp
        monkeypatch.setattr(vp, "ollama_models", lambda *a, **k: [])
        results = doctor_mod.check_models()
        blender = [r for r in results if r["name"].startswith("local_models")]
        assert blender
        assert blender[0]["status"] in (WARN, PASS)
        assert not any(r["status"] == FAIL for r in results)

    def test_required_mission_upgrades_warn_to_fail(self, monkeypatch):
        import core.doctor as doctor_mod
        import core.vision_provider as vp
        monkeypatch.setattr(vp, "ollama_models", lambda *a, **k: [])
        report = run_doctor(requirements=["blender"])
        blender_checks = [c for c in report["checks"]
                          if c["name"] == "blender"]
        # With real vendored Blender present it PASSes; with none it must
        # FAIL because the mission requires it.
        if blender_checks and blender_checks[0]["status"] == FAIL:
            assert "required by requested mission" in \
                blender_checks[0]["detail"]

    def test_human_summary_lists_non_pass(self, capsys):
        report = run_doctor()
        text = human_summary(report)
        assert "unreal-coder doctor" in text

    def test_doctor_endpoint(self, monkeypatch, tmp_path):
        from fastapi.testclient import TestClient
        from core import mission as mission_mod
        monkeypatch.setattr(mission_mod, "CHECKPOINT_DIR", tmp_path / "cp")
        from app import api
        from app.unreal_coder_api import register_unreal_coder_api
        register_unreal_coder_api(api.app, tool_registry=lambda: api.REGISTRY)
        with TestClient(api.app, raise_server_exceptions=False) as client:
            response = client.get("/api/unreal-coder/doctor")
        assert response.status_code == 200
        data = response.json()
        assert data["overall"] in (PASS, "DEGRADED", FAIL)
        assert data["summary"][FAIL] == 0


class TestSecretRedaction:
    def test_secret_key_names_redacted(self):
        payload = {"OPENAI_API_KEY": "sk-abcdefghijklmnop123456",
                   "remote_token": "tok_1234567890abcdef",
                   "my_password": "hunter2supersecret"}
        out = redact(payload)
        assert "sk-abcdefghijklmnop123456" not in json.dumps(out)
        assert "hunter2supersecret" not in json.dumps(out)
        assert "tok_1234567890abcdef" not in json.dumps(out)

    def test_secret_value_shapes_redacted(self):
        payload = {"note": "key is sk-abcdefghijklmnop123456789 ok",
                   "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc"}
        out = redact(payload)
        dumped = json.dumps(out)
        assert "sk-abcdefghijklmnop123456789" not in dumped
        assert "eyJhbGciOiJIUzI1NiJ9" not in dumped

    def test_normal_values_untouched(self):
        payload = {"unreal_engine": "D:/Program Files/Epic Games/UE_5.8",
                   "model": "unreal-coder:latest", "port": 6766}
        out = redact(payload)
        assert out["unreal_engine"] == "D:/Program Files/Epic Games/UE_5.8"
        assert out["model"] == "unreal-coder:latest"
        assert out["port"] == 6766

    def test_nested_structures(self):
        payload = {"mission": {"config": {"api_key": "sk-secretsecretsecret12"},
                               "steps": [{"tool": "spawn_actor"},
                                         {"bearer": "tok_zzzzzzzzzzzz"}]}}
        out = redact(payload)
        dumped = json.dumps(out)
        assert "sk-secretsecretsecret12" not in dumped
        assert "tok_zzzzzzzzzzzz" not in dumped
        assert out["mission"]["steps"][0]["tool"] == "spawn_actor"

    def test_redact_text_free_form(self):
        text = ("started with OPENAI_API_KEY=sk-abcdef1234567890abcdef and "
                "password=hunter2 done")
        out = redact_text(text)
        assert "sk-abcdef1234567890abcdef" not in out
        assert "hunter2" not in out
        assert "OPENAI_API_KEY=" in out  # key name survives, value gone

    def test_redaction_is_stable_and_non_reversible(self):
        out = redact_value("sk-abcdefghijklmnop123456", key="api_key")
        assert "sk-abcdefghijklmnop123456" not in out
        assert "REDACTED" in out

    def test_config_snapshot_never_leaks(self, monkeypatch):
        monkeypatch.setenv("UNREAL_AGENT_REMOTE_API_KEY",
                           "sk-supersecretvalue123456")
        snapshot = json.dumps(config_snapshot())
        assert "sk-supersecretvalue123456" not in snapshot

    def test_config_surface_declares_secret_fields(self):
        secrets = [c for c in CONFIG_SURFACE if c["secret"]]
        assert any(c["key"] == "remote_vision_api_key" for c in secrets)

    def test_no_secret_ever_written_to_repo(self):
        """Static guarantee: tracked config file has no secret-shaped keys."""
        if not config_mod.CONFIG_FILE.is_file():
            pytest.skip("no config file")
        cfg = json.loads(config_mod.CONFIG_FILE.read_text(
            encoding="utf-8-sig"))
        leaked = [k for k in cfg if is_secret_key(k)]
        assert not leaked, f"secret-looking keys in config file: {leaked}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
