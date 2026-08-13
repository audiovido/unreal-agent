import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = ROOT / "config" / "settings.json"

with open(SETTINGS_PATH, "r", encoding="utf-8-sig") as f:
    SETTINGS = json.load(f)

UNREAL_ENGINE = Path(SETTINGS["unreal_engine"])
UNREAL_EDITOR = UNREAL_ENGINE / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe"


def read_text_file(path: str) -> str:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return f"ERROR: file does not exist: {p}"
    if not p.is_file():
        return f"ERROR: path is not a file: {p}"

    try:
        return p.read_text(encoding="utf-8-sig", errors="replace")
    except Exception as e:
        return f"ERROR: {e}"


def write_text_file(path: str, content: str) -> str:
    p = Path(path).expanduser().resolve()

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8-sig")
        return f"OK: wrote {p}"
    except Exception as e:
        return f"ERROR: {e}"


def run_powershell(command: str, timeout: int = 120) -> dict:
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command
            ],
            capture_output=True,
            text=True,
            timeout=timeout
        )

        return {
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip()
        }

    except subprocess.TimeoutExpired:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"Command timed out after {timeout} seconds"
        }

    except Exception as e:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": str(e)
        }


def find_unreal_projects(search_root: str) -> list[str]:
    root = Path(search_root).expanduser().resolve()

    if not root.exists():
        return []

    projects = []

    for p in root.rglob("*.uproject"):
        projects.append(str(p))

    return projects


def unreal_status() -> dict:
    return {
        "engine_root": str(UNREAL_ENGINE),
        "editor_exe": str(UNREAL_EDITOR),
        "editor_exists": UNREAL_EDITOR.exists()
    }


def launch_unreal_project(uproject_path: str) -> dict:
    project = Path(uproject_path).expanduser().resolve()

    if not project.exists():
        return {
            "ok": False,
            "error": f"Project not found: {project}"
        }

    if not UNREAL_EDITOR.exists():
        return {
            "ok": False,
            "error": f"UnrealEditor.exe not found: {UNREAL_EDITOR}"
        }

    try:
        subprocess.Popen(
            [str(UNREAL_EDITOR), str(project)],
            cwd=str(project.parent)
        )

        return {
            "ok": True,
            "project": str(project),
            "editor": str(UNREAL_EDITOR)
        }

    except Exception as e:
        return {
            "ok": False,
            "error": str(e)
        }


if __name__ == "__main__":
    print("=== Unreal Agent Tool System ===")
    print(json.dumps(unreal_status(), indent=2))

    print("\n=== Searching for Unreal projects ===")
    projects = find_unreal_projects(str(Path.home()))

    for p in projects[:20]:
        print(p)

    print(f"\nFound {len(projects)} project(s).")

