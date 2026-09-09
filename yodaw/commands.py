"""Command execution primitives for YODAW.

The API accepts a structured request and never builds a shell command by
concatenating untrusted fields.  Shell mode is explicit and the working
 directory is constrained to an allowed workspace root.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Mapping, Sequence


@dataclass(slots=True)
class CommandRequest:
    target: str = "local"
    cwd: str = "."
    command: str | Sequence[str] = ""
    env: Mapping[str, str] = field(default_factory=dict)
    timeout: float = 120.0
    shell: bool = False
    allowed_root: str | None = None


@dataclass(slots=True)
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    target: str = "local"
    command: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _safe_cwd(cwd: str, allowed_root: str | None) -> Path:
    path = Path(cwd).expanduser().resolve()
    if allowed_root is not None:
        root = Path(allowed_root).expanduser().resolve()
        if path != root and root not in path.parents:
            raise ValueError(f"cwd escapes allowed workspace: {path}")
    if not path.is_dir():
        raise ValueError(f"cwd is not a directory: {path}")
    return path


def _argv(command: str | Sequence[str], shell: bool) -> str | list[str]:
    if isinstance(command, str):
        if shell:
            return command
        # shlex is only tokenization; execution remains shell=False.
        return shlex.split(command, posix=os.name != "nt")
    return [str(x) for x in command]


def run_local(request: CommandRequest) -> CommandResult:
    if not request.command:
        raise ValueError("command is required")
    cwd = _safe_cwd(request.cwd, request.allowed_root)
    argv = _argv(request.command, request.shell)
    merged_env = os.environ.copy()
    merged_env.update({str(k): str(v) for k, v in request.env.items()})
    started = time.perf_counter()
    timed_out = False
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd),
            env=merged_env,
            shell=bool(request.shell),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(0.01, float(request.timeout)),
        )
        code = proc.returncode
        stdout, stderr = proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        code = 124
        stdout = _decode(exc.stdout)
        stderr = _decode(exc.stderr) or "command timed out"
    duration_ms = int((time.perf_counter() - started) * 1000)
    return CommandResult(code, stdout, stderr, duration_ms, timed_out,
                         request.target, request.command if isinstance(request.command, str) else " ".join(request.command))


def _decode(value: object) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)


class LocalCommandAdapter:
    def run_command(self, request: CommandRequest) -> CommandResult:
        request.target = "local"
        return run_local(request)
