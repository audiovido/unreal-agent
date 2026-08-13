import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = ROOT / "config" / "settings.json"

with open(SETTINGS_PATH, "r", encoding="utf-8-sig") as f:
    SETTINGS = json.load(f)

UNREAL_ENGINE = Path(SETTINGS["unreal_engine"])
UNREAL_EDITOR = UNREAL_ENGINE / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe"


def discover_projects(search_roots=None):
    if search_roots is None:
        home = Path.home()
        search_roots = [
            home / "Desktop",
            home / "Documents",
            home / "Downloads",
        ]

    results = []

    for root in search_roots:
        root = Path(root)
        if not root.exists():
            continue

        for p in root.rglob("*.uproject"):
            results.append(str(p.resolve()))

    return sorted(set(results))


def inspect_project(uproject_path: str):
    p = Path(uproject_path).resolve()

    if not p.exists():
        return {"ok": False, "error": "uproject not found"}

    data = {}

    try:
        data["uproject"] = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception as e:
        data["uproject_parse_error"] = str(e)

    project_root = p.parent

    data.update({
        "ok": True,
        "name": p.stem,
        "uproject_path": str(p),
        "project_root": str(project_root),
        "has_source": (project_root / "Source").exists(),
        "has_content": (project_root / "Content").exists(),
        "has_config": (project_root / "Config").exists(),
        "has_plugins": (project_root / "Plugins").exists(),
        "has_saved": (project_root / "Saved").exists(),
    })

    return data


def open_project(uproject_path: str):
    p = Path(uproject_path).resolve()

    if not p.exists():
        return {"ok": False, "error": f"Project not found: {p}"}

    if not UNREAL_EDITOR.exists():
        return {"ok": False, "error": f"UnrealEditor.exe not found: {UNREAL_EDITOR}"}

    subprocess.Popen([str(UNREAL_EDITOR), str(p)], cwd=str(p.parent))

    return {"ok": True, "opened": str(p)}


def create_project(project_name: str, destination: str, template="Blank"):
    destination = Path(destination).expanduser().resolve()
    project_root = destination / project_name
    project_root.mkdir(parents=True, exist_ok=True)

    uproject_path = project_root / f"{project_name}.uproject"

    if uproject_path.exists():
        return {
            "ok": False,
            "error": f"Project already exists: {uproject_path}"
        }

    descriptor = {
        "FileVersion": 3,
        "EngineAssociation": "5.8",
        "Category": "",
        "Description": "",
        "Modules": []
    }

    uproject_path.write_text(
        json.dumps(descriptor, indent=2),
        encoding="utf-8"
    )

    for folder in ["Content", "Config", "Source", "Plugins"]:
        (project_root / folder).mkdir(exist_ok=True)

    return {
        "ok": True,
        "project_name": project_name,
        "project_root": str(project_root),
        "uproject_path": str(uproject_path),
        "template": template,
        "note": "Base Unreal project structure created. Editor/template automation comes next."
    }


if __name__ == "__main__":
    print("=== Unreal Project Manager ===")
    projects = discover_projects()

    print(f"Found {len(projects)} project(s):")
    for p in projects:
        print(p)
