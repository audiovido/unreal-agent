"""Concurrent mission supervisor for YODAW Code Core."""
from __future__ import annotations

import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from .commands import CommandRequest, run_local
from .git import integrate, push_current
from .plan import WorkerPlan, plan_from_request
from .retry import RetryEngine, ValidationEvidence
from .workspaces import WorkspaceManager

WORKER_STATES = {"QUEUED", "RUNNING", "WAITING", "PASS", "FAILED", "BLOCKED", "CANCELLED"}


@dataclass(slots=True)
class WorkerResult:
    worker_id: str
    state: str
    attempt: int = 0
    changed_files: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    commit_sha: str | None = None
    branch: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MissionCancelled(RuntimeError):
    pass


class MissionOrchestrator:
    def __init__(self, *, workspace_manager: WorkspaceManager, max_workers: int = 4,
                 update: Callable[..., None] | None = None,
                 cancelled: Callable[[], bool] | None = None):
        self.workspaces = workspace_manager
        self.max_workers = max(1, int(max_workers))
        self.update = update or (lambda **kwargs: None)
        self.cancelled = cancelled or (lambda: False)
        self._lock = threading.RLock()

    def run(self, *, mission_id: str, repo: str, prompt: str,
            raw_plan: list[dict[str, Any]] | None = None,
            auto_commit: bool = True, auto_push: bool = False,
            remote: str = "origin") -> dict[str, Any]:
        try:
            plans = plan_from_request(prompt, raw_plan)
        except Exception as exc:
            return {"state": "BLOCKED", "stage": "planning", "blockers": [str(exc)], "workers": []}
        self.update(stage="planning", workers=[self._queued(p) for p in plans])
        results: dict[str, WorkerResult] = {}
        pending = {p.worker_id: p for p in plans}
        accepted: list[WorkerResult] = []
        while pending:
            if self.cancelled():
                for plan in pending.values():
                    results[plan.worker_id] = WorkerResult(plan.worker_id, "CANCELLED")
                return {"state": "CANCELLED", "stage": "cancelled", "workers": [r.to_dict() for r in results.values()]}
            done_ids = {worker_id for worker_id, result in results.items() if result.state == "PASS"}
            failed_ids = {worker_id for worker_id, result in results.items() if result.state in {"FAILED", "BLOCKED", "CANCELLED"}}
            ready = [p for p in pending.values() if all(d in done_ids for d in p.depends_on)]
            blocked = [p for p in pending.values() if any(d in failed_ids for d in p.depends_on)]
            for plan in blocked:
                results[plan.worker_id] = WorkerResult(plan.worker_id, "BLOCKED", error="dependency failed")
                pending.pop(plan.worker_id)
            if not ready:
                if pending:
                    # Pending with no failed dependency is a cycle/invalid graph;
                    # planning validation should catch this, but fail honestly.
                    if not blocked:
                        return {"state": "BLOCKED", "stage": "scheduling", "blockers": ["worker dependency graph made no progress"], "workers": [r.to_dict() for r in results.values()]}
                continue
            batch = ready[:self.max_workers]
            for plan in batch:
                pending.pop(plan.worker_id)
                self.update_worker(results, WorkerResult(plan.worker_id, "RUNNING"))
            self.update(stage="workers", workers=[self._queued(p) if p.worker_id in pending else results.get(p.worker_id, WorkerResult(p.worker_id, "RUNNING")).to_dict() for p in plans])
            # Git worktree creation updates shared repository metadata. Do it
            # serially before launching workers; the edit/test phases below
            # still execute concurrently in independent worktrees.
            prepared = []
            for plan in batch:
                try:
                    self.workspaces.create_workspace(
                        f"{mission_id}-{plan.worker_id}", repo,
                        branch=f"yodaw/{mission_id}/{plan.worker_id}",
                    )
                    prepared.append(plan)
                except Exception as exc:
                    results[plan.worker_id] = WorkerResult(plan.worker_id, "FAILED", error=f"workspace preparation failed: {exc}")
                    pending.pop(plan.worker_id, None)
            if not prepared:
                continue
            batch = prepared
            with ThreadPoolExecutor(max_workers=len(batch), thread_name_prefix="yodaw-worker") as executor:
                futures = {executor.submit(self._run_worker, mission_id, repo, plan): plan for plan in batch}
                for future in as_completed(futures):
                    plan = futures[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = WorkerResult(plan.worker_id, "FAILED", error=f"worker crashed: {type(exc).__name__}: {exc}")
                    results[plan.worker_id] = result
                    if result.state == "PASS":
                        accepted.append(result)
                    self.update(stage="workers", workers=[results.get(p.worker_id, self._queued(p)).to_dict() if isinstance(results.get(p.worker_id), WorkerResult) else results.get(p.worker_id, self._queued(p)) for p in plans])
        if any(result.state != "PASS" for result in results.values()):
            return {"state": "FAILED", "stage": "workers", "workers": [r.to_dict() for r in results.values()], "blockers": [r.error for r in results.values() if r.error]}
        if not auto_commit:
            return {"state": "PASS", "stage": "validated", "workers": [r.to_dict() for r in results.values()]}
        self.update(stage="integration")
        # Worker branches are created by _run_worker and retained for merge.
        base = Path(repo).resolve()
        commits = [r for r in accepted if r.commit_sha]
        for result in sorted(commits, key=lambda r: r.worker_id):
            # Integrate branches one at a time. Every merge is checked against
            # the clean base; an accepted worker never mutates the base until
            # this deterministic integration phase.
            integrated = integrate(str(base), str(result.branch), f"integrate {mission_id} {result.worker_id}", push=False)
            if not integrated.ok:
                return {"state": "BLOCKED", "stage": "integration", "workers": [r.to_dict() for r in results.values()], "blockers": [integrated.error]}
            try:
                self.workspaces.cleanup_worktree(f"{mission_id}-{result.worker_id}")
            except RuntimeError:
                # A committed accepted worker should be clean; retain it if a
                # platform-specific cleanup issue occurs for recovery.
                pass
        final = {"state": "PASS", "stage": "complete", "workers": [r.to_dict() for r in results.values()]}
        if auto_push:
            pushed = push_current(str(base), remote=remote)
            final["push_status"] = pushed.push_status
            if not pushed.ok:
                final["state"] = "FAILED"; final["blockers"] = [pushed.error]
        return final

    @staticmethod
    def _queued(plan: WorkerPlan) -> dict[str, Any]:
        return {"worker_id": plan.worker_id, "title": plan.title, "state": "QUEUED", "files": plan.files, "depends_on": plan.depends_on}

    @staticmethod
    def update_worker(results: dict[str, WorkerResult], result: WorkerResult) -> None:
        results[result.worker_id] = result

    def _run_worker(self, mission_id: str, repo: str, plan: WorkerPlan) -> WorkerResult:
        if self.cancelled():
            return WorkerResult(plan.worker_id, "CANCELLED")
        ws = self.workspaces.get(f"{mission_id}-{plan.worker_id}")
        if ws is None:
            return WorkerResult(plan.worker_id, "FAILED", error="worker workspace was not prepared")
        path = Path(ws.path)
        evidence: list[dict[str, Any]] = []
        current_steps = plan.steps
        try:
            for attempt in range(1, len(plan.retry_steps) + 2):
                if self.cancelled():
                    return WorkerResult(plan.worker_id, "CANCELLED", attempt=attempt - 1, evidence=evidence, branch=ws.branch)
                # Retries apply incrementally to the existing attempt in the
                # same worker worktree; never recreate the initial broken plan.
                self._apply_steps(path, current_steps)
                changed = self._changed(path)
                validation = self._validate(path, plan)
                ev = ValidationEvidence(
                    command=validation["command"], exit_code=validation["exit_code"],
                    stdout=validation["stdout"], stderr=validation["stderr"],
                    changed_files=changed, plan_summary=plan.title, attempt=attempt,
                )
                expected = set(plan.files)
                actual = set(changed)
                if ev.exit_code == 0 and self._acceptance(path, plan.acceptance) and actual == expected:
                    evidence.append({"attempt": attempt, "status": "PASS", "evidence": ev.concise()})
                    commit = self._commit(path, plan.title)
                    if not commit:
                        return WorkerResult(plan.worker_id, "FAILED", attempt, changed, evidence, error="verified worker commit failed", branch=ws.branch)
                    return WorkerResult(plan.worker_id, "PASS", attempt, changed, evidence, commit, ws.branch)
                ev.classification = "test_failure"
                evidence.append({"attempt": attempt, "status": "FAIL", "evidence": ev.concise()})
                if attempt > len(plan.retry_steps):
                    return WorkerResult(plan.worker_id, "FAILED", attempt, changed, evidence, error=ev.stderr or "validation failed", branch=ws.branch)
                current_steps = plan.retry_steps[attempt - 1]
            return WorkerResult(plan.worker_id, "FAILED", len(evidence), evidence=evidence, error="retry budget exhausted", branch=ws.branch)
        except Exception as exc:
            return WorkerResult(plan.worker_id, "FAILED", error=f"{type(exc).__name__}: {exc}", evidence=evidence, branch=ws.branch)

    @staticmethod
    def _apply_steps(path: Path, steps: list[dict[str, Any]]) -> None:
        for step in steps:
            rel = str(step.get("path", "")).replace("\\", "/")
            target = (path / rel).resolve()
            if path not in target.parents:
                raise ValueError(f"path escapes worker workspace: {rel}")
            op = step.get("op", "write_file")
            if op == "write_file":
                target.parent.mkdir(parents=True, exist_ok=True)
                # A retry plan can intentionally rewrite a file from its
                # original failed attempt; corrections must remain scoped.
                target.write_text(str(step.get("content", "")), encoding="utf-8")
            elif op == "replace_text":
                content = target.read_text(encoding="utf-8"); old = str(step.get("old", ""))
                if not old or old not in content:
                    raise ValueError(f"replacement text not found: {rel}")
                target.write_text(content.replace(old, str(step.get("new", "")), 1), encoding="utf-8")
            else:
                raise ValueError(f"unsupported edit operation: {op}")

    @staticmethod
    def _changed(path: Path) -> list[str]:
        out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=path, capture_output=True, text=True, check=True)
        return [line[3:].strip().replace("\\", "/") for line in out.stdout.splitlines() if len(line) > 3 and "__pycache__" not in line]

    @staticmethod
    def _validate(path: Path, plan: WorkerPlan) -> dict[str, Any]:
        if not plan.tests:
            return {"command": "acceptance-only", "exit_code": 0, "stdout": "", "stderr": ""}
        # A corrective retry can rewrite a same-size source file within one
        # filesystem timestamp tick. Remove stale bytecode and disable writes
        # so validation observes the accepted source, not attempt-one cache.
        for cache in path.rglob("__pycache__"):
            if cache.is_dir():
                import shutil
                shutil.rmtree(cache, ignore_errors=True)
        spec = plan.tests[0].split()
        result = run_local(CommandRequest(
            cwd=str(path), allowed_root=str(path), command=spec, timeout=300,
            env={"PYTHONDONTWRITEBYTECODE": "1"},
        ))
        return {"command": " ".join(spec), "exit_code": result.exit_code, "stdout": result.stdout, "stderr": result.stderr}

    @staticmethod
    def _acceptance(path: Path, conditions: list[str]) -> bool:
        for cond in conditions:
            if cond.startswith("exists ") and not (path / cond[7:].strip()).is_file():
                return False
            if cond.startswith("contains "):
                rel, _, needle = cond[9:].partition("|")
                try: content = (path / rel.strip()).read_text(encoding="utf-8")
                except OSError: return False
                if needle not in content: return False
        return True

    @staticmethod
    def _commit(path: Path, title: str) -> str | None:
        subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True)
        result = subprocess.run(["git", "-c", "user.name=YODAW Worker", "-c", "user.email=yodaw@local", "commit", "-m", title], cwd=path, capture_output=True, text=True)
        if result.returncode != 0: return None
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True, check=True)
        return result.stdout.strip()
