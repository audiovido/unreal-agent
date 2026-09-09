"""Persistent mission records and lifecycle state."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .workspaces import WorkspaceManager

MISSION_STATES = {"CREATED", "RUNNING", "BLOCKED", "FAILED", "PASS", "CANCELLED", "RECOVERING"}


@dataclass(slots=True)
class Mission:
    mission_id: str
    prompt: str
    repo: str
    target: str = "local"
    state: str = "CREATED"
    stage: str = "planning"
    max_workers: int = 4
    auto_commit: bool = True
    auto_push: bool = False
    plan: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    current_attempt: int = 0
    changed_files: list[str] = field(default_factory=list)
    tests: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    workers: list[dict[str, Any]] = field(default_factory=list)
    commit_sha: str | None = None
    branch: str | None = None
    remote: str | None = None
    push_status: str = "not_requested"
    blockers: list[str] = field(default_factory=list)
    cancel_requested: bool = False


class MissionStore:
    def __init__(self, state_dir: str | Path, workspace_manager: WorkspaceManager | None = None):
        self.dir = Path(state_dir).resolve(); self.dir.mkdir(parents=True, exist_ok=True)
        self.file = self.dir / "missions.json"
        self.lock = threading.RLock()
        self.workspaces = workspace_manager or WorkspaceManager(self.dir)

    def _load(self) -> dict[str, Any]:
        if not self.file.exists(): return {"missions": {}}
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
            return data if isinstance(data.get("missions"), dict) else {"missions": {}}
        except (OSError, ValueError): return {"missions": {}}

    def _save(self, data: dict[str, Any]) -> None:
        tmp = self.file.with_suffix(f".{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, self.file)

    def create(self, prompt: str, repo: str, **kwargs: Any) -> Mission:
        allowed = {k: v for k, v in kwargs.items() if k in Mission.__dataclass_fields__}
        mission = Mission(uuid.uuid4().hex, prompt, repo, **allowed)
        with self.lock:
            data = self._load(); data["missions"][mission.mission_id] = asdict(mission); self._save(data)
        return mission

    def get(self, mission_id: str) -> Mission | None:
        with self.lock:
            raw = self._load()["missions"].get(mission_id)
            return Mission(**raw) if raw else None

    def update(self, mission_id: str, **fields: Any) -> Mission:
        with self.lock:
            data = self._load(); raw = data["missions"].get(mission_id)
            if not raw: raise KeyError(mission_id)
            raw.update(fields); raw["updated_at"] = time.time(); self._save(data)
            return Mission(**raw)

    def append_evidence(self, mission_id: str, evidence: dict[str, Any]) -> Mission:
        mission = self.get(mission_id)
        if mission is None: raise KeyError(mission_id)
        return self.update(mission_id, evidence=[*mission.evidence, {"at": time.time(), **evidence}])

    def list(self) -> list[Mission]:
        with self.lock: return [Mission(**x) for x in self._load()["missions"].values()]

    def evidence(self, mission_id: str) -> list[dict[str, Any]]:
        mission = self.get(mission_id)
        if mission is None: raise KeyError(mission_id)
        return mission.evidence

    def request_cancel(self, mission_id: str) -> Mission:
        mission = self.get(mission_id)
        if mission is None: raise KeyError(mission_id)
        if mission.state in {"PASS", "FAILED", "BLOCKED", "CANCELLED"}:
            return mission
        return self.update(mission_id, cancel_requested=True, state="CANCELLED", stage="cancelled")

    def recover(self) -> list[str]:
        recovered = []
        for mission in self.list():
            if mission.state == "RUNNING":
                self.update(mission.mission_id, state="RECOVERING", stage="recovery")
                recovered.append(mission.mission_id)
        return recovered
