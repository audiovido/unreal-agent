import json
from pathlib import Path
from unittest.mock import patch

from tools.unreal import project_manager


def test_create_project_prepares_blank_project_and_opens_it(tmp_path):
    with patch.object(
        project_manager,
        "open_project",
        return_value={
            "ok": True,
            "editor_pid": 1234,
            "bridge_ready": True,
            "project_identity": {
                "project_name": "UA_ProjectCreation_Test",
            },
        },
    ) as open_project:
        result = project_manager.create_project(
            "UA_ProjectCreation_Test",
            str(tmp_path),
        )

    root = tmp_path / "UA_ProjectCreation_Test"
    descriptor = json.loads(
        (root / "UA_ProjectCreation_Test.uproject").read_text(
            encoding="utf-8"
        )
    )

    assert result["ok"] is True
    assert result["opened"] is True
    assert open_project.call_args.args[0].endswith(
        "UA_ProjectCreation_Test.uproject"
    )
    assert descriptor["EngineAssociation"] == "5.8"
    assert any(
        plugin["Name"] == "PythonScriptPlugin"
        and plugin["Enabled"] is True
        for plugin in descriptor["Plugins"]
    )
    assert (root / "Content" / "Python" / "init_unreal.py").is_file()
    assert "EditorStartupMap=/Game/UA_ProjectCreation_Test" in (
        root / "Config" / "DefaultEngine.ini"
    ).read_text(encoding="utf-8")


def test_create_project_refuses_existing_directory(tmp_path):
    root = tmp_path / "UA_ProjectCreation_Test"
    root.mkdir()

    result = project_manager.create_project(
        "UA_ProjectCreation_Test",
        str(tmp_path),
    )

    assert result["ok"] is False
    assert "refusing to overwrite" in result["error"]
