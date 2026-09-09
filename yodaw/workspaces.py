"""Isolated mission worktree lifecycle."""
from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(slots=True)
class Workspace:
    mission_id: str
    repo: str
    path: str
    branch: str
    status: str = "CREATED"
    created_at: float = 0.0
    updated_at: float = 0.0


class WorkspaceManager:
    def __init__(self, state_dir: str | Path, worktree_root: str | Path | None = None):
        self.state_dir = Path(state_dir).resolve()
        self.root = Path(worktree_root or self.state_dir / "worktrees").resolve()
        self.state_file = self.state_dir / "workspaces.json"
        self.lock = __import__("threading").RLock()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.root.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict:
        if not self.state_file.exists():
            return {"workspaces": {}}
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            return data if isinstance(data.get("workspaces"), dict) else {"workspaces": {}}
        except Exception:
            return {"workspaces": {}}

    def _save(self, data: dict) -> None:
        tmp = self.state_file.with_suffix(f".{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, self.state_file)

    def _git(self, repo: Path, *args: str, timeout: int = 60) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, timeout=timeout)

    def create_workspace(self, mission_id: str, repo: str, branch: str | None = None) -> Workspace:
        with self.lock:
            return self._create_workspace_locked(mission_id, repo, branch)

    def _create_workspace_locked(self, mission_id: str, repo: str, branch: str | None = None) -> Workspace:
        repo_path = Path(repo).expanduser().resolve()
        if not (repo_path / ".git").exists() and self._git(repo_path, "rev-parse", "--git-dir").returncode != 0:
            raise ValueError(f"not a git repository: {repo_path}")
        data = self._load()
        existing = data["workspaces"].get(mission_id)
        if existing and Path(existing["path"]).exists():
            existing_obj = Workspace(**existing)
            existing_obj.updated_at = time.time()
            data["workspaces"][mission_id] = asdict(existing_obj)
            self._save(data)
            return existing_obj
        branch = branch or f"yodaw/mission/{mission_id}"
        path = self.root / mission_id
        if path.exists():
            raise RuntimeError(f"workspace path exists but is not registered: {path}")
        proc = self._git(repo_path, "worktree", "add", "-b", branch, str(path), "HEAD", timeout=180)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout).strip())
        now = time.time()
        ws = Workspace(mission_id, str(repo_path), str(path), branch, "CREATED", now, now)
        data["workspaces"][mission_id] = asdict(ws)
        self._save(data)
        return ws

    def get(self, mission_id: str) -> Workspace | None:
        item = self._load()["workspaces"].get(mission_id)
        return Workspace(**item) if item else None

    def list_worktrees(self) -> list[Workspace]:
        return [Workspace(**item) for item in self._load()["workspaces"].values()]

    def set_status(self, mission_id: str, status: str) -> Workspace:
        ws = self.get(mission_id)
        if ws is None:
            raise KeyError(mission_id)
        ws.status, ws.updated_at = status, time.time()
        data = self._load(); data["workspaces"][mission_id] = asdict(ws); self._save(data)
        return ws

    def cleanup_worktree(self, mission_id: str, force: bool = False) -> bool:
        with self.lock:
            return self._cleanup_worktree_locked(mission_id, force)

    def _cleanup_worktree_locked(self, mission_id: str, force: bool = False) -> bool:
        ws = self.get(mission_id)
        if ws is None:
            return False
        path, repo = Path(ws.path), Path(ws.repo)
        if path.exists() and not force:
            dirty = self._git(path, "status", "--porcelain", "--untracked-files=all")
            if dirty.returncode != 0:
                raise RuntimeError(dirty.stderr or "cannot inspect worktree")
            if dirty.stdout.strip():
                raise RuntimeError(f"refusing to delete dirty workspace: {path}")
        proc = self._git(repo, "worktree", "remove", "--force" if force else "--", str(path), timeout=120)
        if proc.returncode != 0 and path.exists():
            raise RuntimeError((proc.stderr or proc.stdout).strip())
        data = self._load(); data["workspaces"].pop(mission_id, None); self._save(data)
        return True

    def gc_stale_worktrees(self, max_age_s: float, now: float | None = None) -> list[str]:
        now = now or time.time(); removed = []
        for ws in self.list_worktrees():
            if now - ws.updated_at <= max_age_s or ws.status in {"RUNNING", "BLOCKED"}:
                continue
            try:
                self.cleanup_worktree(ws.mission_id, force=False)
                removed.append(ws.mission_id)
            except RuntimeError:
                # Dirty workspaces are intentionally retained for recovery.
                continue
        return removed
