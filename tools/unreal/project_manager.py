import json
import shutil
import subprocess
import socket
import time
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


def _bridge_socket_ready(host="127.0.0.1", port=6766, timeout=1.0):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _normalized_path(value):
    return str(value or "").replace("\\", "/").casefold()


def _bridge_identity(bridge):
    try:
        result = bridge.execute_python(r'''
project_path = str(unreal.Paths.get_project_file_path()).replace(chr(92), "/")
project_name = project_path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
__bridge_result__ = {
    "project_path": project_path,
    "project_name": project_name,
}
''')
        payload = result.get("result") if isinstance(result, dict) else None
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _bridge_owner_pid(port=6766):
    # netstat is preferred: it starts instantly and does not depend on
    # PowerShell cold-start, which can exceed short subprocess timeouts.
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[0] == "TCP" and parts[1].endswith(f":{port}") and parts[3] == "LISTENING":
                pid = parts[4].strip()
                if pid.isdigit():
                    return int(pid)
    except Exception:
        pass
    return None


def _stop_current_editor():
    pid = _bridge_owner_pid()
    if pid is None:
        return {"ok": False, "error": "Could not identify the editor owning the Unreal bridge"}

    try:
        try:
            from tools.unreal.unreal_bridge import UnrealBridge
            UnrealBridge(timeout=5).execute_python(
                "unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)"
            )
        except Exception:
            pass
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception as exc:
        return {"ok": False, "pid": pid, "error": str(exc)}

    deadline = time.time() + 20
    while time.time() < deadline:
        if not _bridge_socket_ready():
            return {"ok": True, "pid": pid, "stopped": True}
        time.sleep(1)
    return {"ok": False, "pid": pid, "error": "Editor bridge remained open after stop"}


def _wait_for_bridge(host="127.0.0.1", port=6766, timeout_seconds=420, expected_project=None):
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        if _bridge_socket_ready(host, port):
            try:
                from tools.unreal.unreal_bridge import UnrealBridge

                bridge = UnrealBridge(host=host, port=port, timeout=5)
                result = bridge.ping()
                identity = _bridge_identity(bridge)
                if isinstance(result, dict) and result.get("ok"):
                    if expected_project and _normalized_path(identity.get("project_path")) != _normalized_path(expected_project):
                        time.sleep(2)
                        continue
                    return {
                        "ok": True,
                        "bridge_ready": True,
                        "bridge_ping": result,
                        "project_identity": identity,
                    }
            except Exception:
                pass
        time.sleep(2)

    return {
        "ok": False,
        "bridge_ready": False,
        "error": (
            f"Unreal Editor launched but Unreal Agent bridge "
            f"did not become ready on {host}:{port} "
            f"for project {expected_project or 'the requested project'} "
            f"within {timeout_seconds}s"
        ),
    }


def open_project(uproject_path: str):
    p = Path(uproject_path).resolve()

    if not p.exists():
        return {
            "ok": False,
            "error": f"Project not found: {p}",
        }

    if not UNREAL_EDITOR.exists():
        return {
            "ok": False,
            "error": f"UnrealEditor.exe not found: {UNREAL_EDITOR}",
        }

    # Reuse the editor only when its live project identity matches exactly.
    if _bridge_socket_ready():
        from tools.unreal.unreal_bridge import UnrealBridge
        bridge = UnrealBridge(timeout=5)
        current = _bridge_identity(bridge)
        current_path = _normalized_path(current.get("project_path"))
        if current_path == _normalized_path(p):
            ready = _wait_for_bridge(timeout_seconds=8, expected_project=str(p))
            if ready.get("ok"):
                return {
                    "ok": True,
                    "opened": str(p),
                    "already_running": True,
                    **ready,
                }
        else:
            stopped = _stop_current_editor()
            if not stopped.get("ok"):
                return {
                    "ok": False,
                    "error": "A different Unreal project is open and could not be stopped safely",
                    "current_project": current,
                    "stop_result": stopped,
                }

    proc = subprocess.Popen(
        [str(UNREAL_EDITOR), str(p)],
        cwd=str(p.parent),
    )

    ready = _wait_for_bridge(timeout_seconds=420, expected_project=str(p))

    if not ready.get("ok"):
        return {
            "ok": False,
            "opened": str(p),
            "editor_pid": proc.pid,
            **ready,
        }

    return {
        "ok": True,
        "opened": str(p),
        "editor_pid": proc.pid,
        **ready,
    }


def create_project(project_name: str, destination: str, template="Blank"):
    project_name = str(project_name or "").strip()
    if not project_name or any(char in project_name for char in '\\\\/:*?\"<>|'):
        return {"ok": False, "error": f"Invalid Unreal project name: {project_name}"}

    destination = Path(destination).expanduser().resolve()
    project_root = destination / project_name
    uproject_path = project_root / f"{project_name}.uproject"

    if project_root.exists():
        return {
            "ok": False,
            "error": f"Project directory already exists; refusing to overwrite: {project_root}",
            "project_root": str(project_root),
        }

    project_root.mkdir(parents=True, exist_ok=False)
    for folder in ["Content", "Config", "Source", "Plugins"]:
        (project_root / folder).mkdir()

    descriptor = {
        "FileVersion": 3,
        "EngineAssociation": "5.8",
        "Category": "Games",
        "Description": "Disposable Unreal Agent project-creation graduation test",
        "Modules": [],
        "Plugins": [
            {
                "Name": "PythonScriptPlugin",
                "Enabled": True,
                "TargetAllowList": ["Editor"],
            }
        ],
    }
    uproject_path.write_text(json.dumps(descriptor, indent=2), encoding="utf-8")

    (project_root / "Config" / "DefaultEngine.ini").write_text(
        "[/Script/EngineSettings.GameMapsSettings]\n"
        f"GameDefaultMap=/Game/{project_name}\n"
        f"EditorStartupMap=/Game/{project_name}\n",
        encoding="utf-8",
    )

    source_bootstrap = ROOT.parent / "app" / "AudioVidoLivingCity" / "Content" / "Python" / "init_unreal.py"
    target_bootstrap = project_root / "Content" / "Python" / "init_unreal.py"
    if not source_bootstrap.exists():
        return {"ok": False, "error": f"Known-good Unreal bridge bootstrap not found: {source_bootstrap}"}
    target_bootstrap.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_bootstrap, target_bootstrap)

    opened = open_project(str(uproject_path))
    if not opened.get("ok"):
        return {
            "ok": False,
            "project_name": project_name,
            "project_root": str(project_root),
            "uproject_path": str(uproject_path),
            "template": template,
            "open_result": opened,
        }

    return {
        "ok": True,
        "project_name": project_name,
        "project_root": str(project_root),
        "uproject_path": str(uproject_path),
        "template": template,
        "opened": True,
        "editor_pid": opened.get("editor_pid"),
        "bridge_ready": opened.get("bridge_ready"),
        "project_identity": opened.get("project_identity"),
    }


if __name__ == "__main__":
    print("=== Unreal Project Manager ===")
    projects = discover_projects()

    print(f"Found {len(projects)} project(s):")
    for p in projects:
        print(p)
