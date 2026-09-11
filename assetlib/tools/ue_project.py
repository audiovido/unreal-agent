"""FREEBUFF ASSET: disposable Unreal project creation (files only).

Creates a minimal, isolated UE project under assetlib/tests/ue/ — no bridge
plugin, no Python startup scripts, no fixed-port listeners, no code modules.
The editor is opened separately by ue_exec.py so AV/AL editors are never
stopped or touched.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ASSETLIB = TOOLS.parent
if str(ASSETLIB.parent) not in sys.path:
    sys.path.insert(0, str(ASSETLIB.parent))
from assetlib.tools.env import discover_unreal, ensure_layout  # noqa: E402

_VALID_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def create_ue_project(project_name: str, engine_association: str = "5.8") -> dict:
    """Write a disposable Blank-style project; return descriptor info."""
    if not _VALID_NAME.match(project_name):
        return {"ok": False, "error": f"invalid project name: {project_name}"}
    layout = ensure_layout()
    unreal = discover_unreal()
    dest = Path(layout["tests_ue"]) / project_name
    uproject_path = dest / f"{project_name}.uproject"
    if dest.exists():
        return {"ok": False, "error": f"project already exists: {dest}", "uproject_path": str(uproject_path)}
    for folder in ("Content", "Config", "Saved"):
        (dest / folder).mkdir(parents=True, exist_ok=True)

    descriptor = {
        "FileVersion": 3,
        "EngineAssociation": engine_association,
        "Category": "AssetLibraryTests",
        "Description": "Disposable FREEBUFF ASSET test project (isolated, no bridge).",
        "Modules": [],
        "Plugins": [
            {"Name": "PythonScriptPlugin", "Enabled": True, "TargetAllowList": ["Editor"]},
        ],
    }
    uproject_path.write_text(json.dumps(descriptor, indent=2), encoding="utf-8")

    (dest / "Config" / "DefaultEngine.ini").write_text(
        "[/Script/EngineSettings.GameMapsSettings]\n"
        "GameDefaultMap=/Game/EmptyMap\n"
        "EditorStartupMap=/Game/EmptyMap\n"
        "\n"
        "[/Script/Engine.RendererSettings]\n"
        "r.GenerateMeshDistanceFields=True\n"
        "\n"
        "[/Script/HardwareTargeting.HardwareTargetingSettings]\n"
        "TargetedHardwareClass=Desktop\n"
        "AppliedTargetedHardwareClass=Desktop\n"
        "DefaultGraphicsPerformance=Maximum\n"
        "AppliedDefaultGraphicsPerformance=Maximum\n",
        encoding="utf-8",
    )
    (dest / "Config" / "DefaultEditorPerProjectUserSettings.ini").write_text(
        "[/Script/PythonScriptPlugin.PythonScriptPluginUserSettings]\n"
        "EnablePythonOverride=Enable\n",
        encoding="utf-8",
    )
    (dest / "Config" / "DefaultGame.ini").write_text(
        "[/Script/EngineSettings.GeneralProjectSettings]\n"
        "ProjectID=" + _new_guid() + "\n"
        "ProjectName=" + project_name + "\n"
        "Description=FREEBUFF ASSET disposable test project\n",
        encoding="utf-8",
    )
    # Keep shader/DDC work inside the project so no machine-wide cache is touched.
    (dest / "Config" / "DefaultEngine.ini").write_text(
        (dest / "Config" / "DefaultEngine.ini").read_text(encoding="utf-8")
        + "\n[ShaderCompiler]\nLocalShaderCachePath=../../Saved/ShaderCache\n",
        encoding="utf-8",
    )
    return {
        "ok": True,
        "project_name": project_name,
        "project_root": str(dest),
        "uproject_path": str(uproject_path),
        "engine": unreal["engine"],
        "editor": unreal["editor"],
        "cmd": unreal["cmd"],
    }


def _new_guid() -> str:
    import uuid

    return str(uuid.uuid4()).upper()


if __name__ == "__main__":
    import time

    result = create_ue_project("ASSET_" + time.strftime("%Y%m%d_%H%M%S"))
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("ok") else 1)
