"""Reusable mission execution facade."""
from __future__ import annotations

from typing import Any

from .missions import MissionStore
from .orchestrator import MissionOrchestrator


def run_mission(store: MissionStore, mission_id: str) -> dict[str, Any]:
    mission = store.get(mission_id)
    if mission is None:
        raise KeyError(mission_id)
    store.update(mission_id, state="RUNNING", stage="planning")
    result = MissionOrchestrator(
        workspace_manager=store.workspaces,
        max_workers=mission.max_workers,
        cancelled=lambda: bool((store.get(mission_id) or mission).cancel_requested),
        update=lambda **fields: store.update(mission_id, **fields),
    ).run(
        mission_id=mission_id, repo=mission.repo, prompt=mission.prompt,
        raw_plan=mission.plan or None, auto_commit=mission.auto_commit,
        auto_push=mission.auto_push, remote=mission.remote or "origin",
    )
    current = store.get(mission_id)
    if current is not None and not current.cancel_requested:
        workers = result.get("workers", [])
        commits = [w.get("commit_sha") for w in workers if w.get("commit_sha")]
        store.update(
            mission_id, state=result.get("state", "FAILED"),
            stage=result.get("stage", "complete"), workers=workers,
            changed_files=sorted({f for w in workers for f in w.get("changed_files", [])}),
            blockers=result.get("blockers", []),
            commit_sha=commits[-1] if commits else None,
            push_status=result.get("push_status", "not_requested"),
        )
        store.append_evidence(mission_id, {"stage": result.get("stage"), "result": result})
    return result
