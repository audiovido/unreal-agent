"""Machine targets backed by local execution or standard OpenSSH."""
from __future__ import annotations

import os
import posixpath
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .commands import CommandRequest, CommandResult, run_local


@dataclass(slots=True)
class TargetConfig:
    name: str
    type: str = "local"
    host: str | None = None
    user: str | None = None
    port: int = 22
    identity_file: str | None = None
    shell: str | None = None


class TargetAdapter:
    def __init__(self, config: TargetConfig):
        self.config = config

    def run_command(self, request: CommandRequest) -> CommandResult:
        raise NotImplementedError

    def test_connection(self) -> dict[str, Any]:
        result = self.run_command(CommandRequest(target=self.config.name, command=["python", "-c", "print('yodaw-ready')"], timeout=15))
        return {"ok": result.exit_code == 0, "target": self.config.name, "result": result.to_dict()}

    def upload_file(self, local: str, remote: str) -> dict[str, Any]:
        raise NotImplementedError

    def download_file(self, remote: str, local: str) -> dict[str, Any]:
        raise NotImplementedError

    def ensure_repo(self, repo: str) -> dict[str, Any]:
        result = self.run_command(CommandRequest(target=self.config.name, command=["git", "-C", repo, "rev-parse", "--show-toplevel"], timeout=15))
        return {"ok": result.exit_code == 0, "repo": repo, "result": result.to_dict()}

    def get_machine_info(self) -> dict[str, Any]:
        result = self.run_command(CommandRequest(target=self.config.name, command=["python", "-c", "import platform; print(platform.platform())"], timeout=15))
        return {"ok": result.exit_code == 0, "target": self.config.name, "platform": result.stdout.strip(), "result": result.to_dict()}


class LocalTargetAdapter(TargetAdapter):
    def run_command(self, request: CommandRequest) -> CommandResult:
        request.target = self.config.name
        return run_local(request)

    def upload_file(self, local: str, remote: str) -> dict[str, Any]:
        dst = Path(remote).expanduser().resolve()
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local, dst)
        return {"ok": True, "target": self.config.name, "remote": str(dst)}

    def download_file(self, remote: str, local: str) -> dict[str, Any]:
        dst = Path(local).expanduser().resolve()
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(remote, dst)
        return {"ok": True, "target": self.config.name, "local": str(dst)}


class SSHAdapter(TargetAdapter):
    def _prefix(self) -> list[str]:
        if not self.config.host:
            raise ValueError("SSH target requires host")
        destination = f"{self.config.user}@{self.config.host}" if self.config.user else self.config.host
        args = ["ssh", "-p", str(self.config.port), "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
        if self.config.identity_file:
            args += ["-i", os.path.expanduser(self.config.identity_file)]
        return args + [destination]

    def run_command(self, request: CommandRequest) -> CommandResult:
        if not request.command:
            raise ValueError("command is required")
        command = request.command if isinstance(request.command, str) else shlex.join([str(x) for x in request.command])
        if request.cwd and request.cwd != ".":
            command = f"cd -- {shlex.quote(request.cwd)} && {command}"
        if request.env:
            prefix = " ".join(f"{shlex.quote(str(k))}={shlex.quote(str(v))}" for k, v in request.env.items())
            command = f"{prefix} {command}"
        # Remote shell is intentionally explicit: SSH itself invokes the
        # configured remote shell; no local interpolation beyond quoting.
        remote = CommandRequest(target=self.config.name, command=self._prefix() + [command], timeout=request.timeout, shell=False)
        return run_local(remote)

    def upload_file(self, local: str, remote: str) -> dict[str, Any]:
        prefix = ["scp", "-P", str(self.config.port)]
        if self.config.identity_file:
            prefix += ["-i", os.path.expanduser(self.config.identity_file)]
        destination = f"{self.config.user}@{self.config.host}:{remote}" if self.config.user else f"{self.config.host}:{remote}"
        proc = subprocess.run(prefix + [local, destination], capture_output=True, text=True, timeout=120)
        return {"ok": proc.returncode == 0, "target": self.config.name, "stdout": proc.stdout, "stderr": proc.stderr, "exit_code": proc.returncode}

    def download_file(self, remote: str, local: str) -> dict[str, Any]:
        prefix = ["scp", "-P", str(self.config.port)]
        if self.config.identity_file:
            prefix += ["-i", os.path.expanduser(self.config.identity_file)]
        source = f"{self.config.user}@{self.config.host}:{remote}" if self.config.user else f"{self.config.host}:{remote}"
        proc = subprocess.run(prefix + [source, local], capture_output=True, text=True, timeout=120)
        return {"ok": proc.returncode == 0, "target": self.config.name, "stdout": proc.stdout, "stderr": proc.stderr, "exit_code": proc.returncode}


def build_targets(config: dict[str, Any] | None = None) -> dict[str, TargetAdapter]:
    raw = (config or {}).get("targets") or {"local": {"type": "local"}}
    result: dict[str, TargetAdapter] = {}
    for name, value in raw.items():
        value = value or {}
        cfg = TargetConfig(name=name, type=str(value.get("type", "local")), host=value.get("host"), user=value.get("user"), port=int(value.get("port", 22)), identity_file=value.get("identity_file"), shell=value.get("shell"))
        result[name] = SSHAdapter(cfg) if cfg.type == "ssh" else LocalTargetAdapter(cfg)
    return result
