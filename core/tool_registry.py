from dataclasses import dataclass
from typing import Callable, Dict, Any, List

@dataclass
class ToolSpec:
    name: str
    description: str
    args: Dict[str, str]
    func: Callable
    destructive: bool = False

def build_registry(discover_projects, inspect_project, open_project, read_text_file, write_text_file, run_powershell, unreal_status):
    return {
        "discover_projects": ToolSpec(
            name="discover_projects",
            description="Find Unreal .uproject files in common user locations.",
            args={},
            func=discover_projects
        ),
        "inspect_project": ToolSpec(
            name="inspect_project",
            description="Inspect an Unreal project descriptor and key folders.",
            args={
                "uproject_path": "Absolute path to .uproject file"
            },
            func=inspect_project
        ),
        "open_project": ToolSpec(
            name="open_project",
            description="Launch an Unreal project in Unreal Editor.",
            args={
                "uproject_path": "Absolute path to .uproject file"
            },
            func=open_project
        ),
        "read_text_file": ToolSpec(
            name="read_text_file",
            description="Read a UTF-8 text file.",
            args={
                "path": "Absolute or resolvable file path"
            },
            func=read_text_file
        ),
        "write_text_file": ToolSpec(
            name="write_text_file",
            description="Write text to a file.",
            args={
                "path": "Absolute or resolvable file path",
                "content": "Full text content"
            },
            func=write_text_file,
            destructive=True
        ),
        "run_powershell": ToolSpec(
            name="run_powershell",
            description="Run a PowerShell command.",
            args={
                "command": "PowerShell command string",
                "timeout": "Optional timeout in seconds"
            },
            func=run_powershell,
            destructive=True
        ),
        "unreal_status": ToolSpec(
            name="unreal_status",
            description="Return Unreal Engine path and editor availability.",
            args={},
            func=unreal_status
        )
    }

def tool_prompt(registry):
    lines: List[str] = []
    for name, spec in registry.items():
        arg_text = ", ".join(
            f"{k}: {v}" for k, v in spec.args.items()
        ) or "none"

        lines.append(
            f"- {name}({arg_text}) | destructive={spec.destructive} | {spec.description}"
        )

    return "\n".join(lines)

def validate_args(spec: ToolSpec, args: Dict[str, Any]):
    required = set(spec.args.keys())
    provided = set(args.keys())

    missing = required - provided

    if missing:
        return False, f"Missing required args: {sorted(missing)}"

    unknown = provided - required

    if unknown:
        return False, f"Unknown args: {sorted(unknown)}"

    return True, ""
