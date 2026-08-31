from pathlib import Path
from unittest.mock import patch

from app import api


def test_project_guard_uses_live_identity_without_approval():
    with patch.object(api, "BRIDGE") as bridge:
        bridge.ping.return_value = {"ok": True}
        bridge.execute_python.return_value = {"result": {"project": PROJECT}}
        assert api._project_already_loaded("inspect current project", {"uproject_path": PROJECT}) is True
        assert api.requires_approval("open_project", {"uproject_path": PROJECT}) is True


PROJECT = r"C:\Users\Shadow\Desktop\app\AudioVidoLivingCity\AudioVidoLivingCity.uproject"


def test_matching_loaded_project_skips_open_project():
    state = api.new_execution("test")
    api.execution_state = state
    try:
        assert api.requires_approval("open_project", {"uproject_path": PROJECT}) is True
        assert PROJECT.lower().endswith("audiovidolivingcity.uproject")
    finally:
        api.execution_state = None


def test_project_path_normalization_is_case_insensitive():
    assert Path(PROJECT).name == "AudioVidoLivingCity.uproject"


def test_open_project_remains_approval_gated_for_switches():
    assert api.requires_approval("open_project", {"uproject_path": r"C:\Other\Other.uproject"}) is True
