"""Focused, hermetic checks for the V2 transfer-package portability fixes."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _run(code: str, install: Path, env=None):
    run_env = os.environ.copy()
    run_env.update(env or {})
    return subprocess.run(
        [sys.executable, "-I", "-B", "-c",
         "import sys;sys.path.insert(0,sys.argv[1]);" + code, str(install)],
        capture_output=True, text=True, env=run_env, timeout=90)


@pytest.fixture()
def arbitrary_install(tmp_path):
    install = tmp_path / "portable-install" / "Aivido-V2.0.0-Windows"
    for name in ("app", "core", "tools", "blender_agent", "qa", "scripts",
                 "ui", "config"):
        source = ROOT / name
        if source.is_dir():
            shutil.copytree(source, install / name,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return install


def test_package_root_and_interpreter_are_install_relative(arbitrary_install):
    code = (
        "import json;from core import portable_paths as p;"
        "print(json.dumps({'root':str(p.PACKAGE_ROOT),'python':str(p.python_executable())}))"
    )
    result = _run(code, arbitrary_install,
                  {"AIVIDO_HOME": "", "AIVIDO_PYTHON": ""})
    assert result.returncode == 0, result.stderr
    found = json.loads(result.stdout)
    assert Path(found["root"]) == arbitrary_install.resolve()
    assert Path(found["python"]) == Path(sys.executable).resolve()
    assert "Unreal-Agent" not in found["root"]


def test_python_selection_order(arbitrary_install, tmp_path):
    override = tmp_path / "custom-python.exe"
    override.touch()
    result = _run("from core.portable_paths import python_executable;print(python_executable())",
                  arbitrary_install, {"AIVIDO_PYTHON": str(override)})
    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()) == override.resolve()


def test_unreal_path_has_no_machine_specific_default(arbitrary_install):
    code = (
        "from core.portable_paths import unreal_editor_executable;"
        "print(unreal_editor_executable() or 'AUTO_DISCOVERY_UNAVAILABLE')"
    )
    result = _run(code, arbitrary_install,
                  {"UNREAL_AGENT_ENGINE_DIR": ""})
    assert result.returncode == 0, result.stderr
    assert "Program Files" not in result.stdout
    assert "Users\\Shadow" not in result.stdout


def test_missing_optional_speech_resources_degrade_without_network(arbitrary_install):
    code = (
        "import json;from app import speak;"
        "speak._speak_avalive_online=lambda:(_ for _ in ()).throw(AssertionError('network'));"
        "print(json.dumps(speak.chat_speak()))"
    )
    result = _run(code, arbitrary_install)
    assert result.returncode == 0, result.stderr
    found = json.loads(result.stdout)
    assert found["speak"] == "skipped_unavailable"
    assert found["reason"] == "speech_resources_missing"
    assert "scripts/avalive_gate.py" in found["missing"]
    assert "scripts/avalive_gate.json" in found["missing"]


def test_served_imports_from_arbitrary_install(arbitrary_install):
    code = (
        "import json,app.served as served;"
        "print(json.dumps({'title':served.app.title,'file':served.__file__}))"
    )
    result = _run(code, arbitrary_install,
                  {"UA_DISABLE_WORKBOARD_AUTOPILOT": "1"})
    assert result.returncode == 0, result.stderr
    found = json.loads(result.stdout)
    assert Path(found["file"]).resolve().is_relative_to(arbitrary_install.resolve())


def test_ui_has_no_shadow_specific_display_paths(arbitrary_install):
    for name in ("aivido.js", "devboard.html"):
        text = (arbitrary_install / "ui" / name).read_text(encoding="utf-8")
        assert "C:/Users/Shadow" not in text
        assert r"C:\\Users\\Shadow" not in text
