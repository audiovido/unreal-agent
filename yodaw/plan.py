"""Mission planning contracts.

The product accepts explicit worker plans for reliable automation.  A small,
deterministic demo planner is also provided so the end-to-end proof can be
run from one natural-language request without depending on an unavailable
model or inventing edits for arbitrary repositories.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class WorkerPlan:
    worker_id: str
    title: str
    files: list[str]
    steps: list[dict[str, Any]]
    tests: list[str] = field(default_factory=list)
    acceptance: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    retry_steps: list[list[dict[str, Any]]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any], index: int = 0) -> "WorkerPlan":
        worker_id = str(raw.get("worker_id") or raw.get("id") or f"worker-{index + 1}")
        files = [str(x).replace("\\", "/") for x in raw.get("files", [])]
        steps = [dict(x) for x in raw.get("steps", [])]
        if not files:
            files = [str(x.get("path", "")).replace("\\", "/") for x in steps]
        return cls(
            worker_id=worker_id,
            title=str(raw.get("title") or worker_id),
            files=files,
            steps=steps,
            tests=[str(x) for x in raw.get("tests", [])],
            acceptance=[str(x) for x in raw.get("acceptance", [])],
            depends_on=[str(x) for x in raw.get("depends_on", [])],
            retry_steps=[[dict(s) for s in group] for group in raw.get("retry_steps", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id, "title": self.title,
            "files": self.files, "steps": self.steps, "tests": self.tests,
            "acceptance": self.acceptance, "depends_on": self.depends_on,
            "retry_steps": self.retry_steps,
        }


def validate_plan(plans: list[WorkerPlan]) -> None:
    ids = [p.worker_id for p in plans]
    if len(ids) != len(set(ids)):
        raise ValueError("worker ids must be unique")
    known = set(ids)
    for plan in plans:
        if not plan.steps:
            raise ValueError(f"{plan.worker_id} has no edit steps")
        if len(set(plan.files)) != len(plan.files):
            raise ValueError(f"{plan.worker_id} declares duplicate files")
        if not set(plan.files).issuperset({str(s.get("path", "")).replace("\\", "/") for s in plan.steps}):
            raise ValueError(f"{plan.worker_id} steps must stay within files")
        overlap = set(plan.files) & {f for other in plans if other is not plan for f in other.files}
        if overlap:
            raise ValueError(f"workers edit the same files concurrently: {sorted(overlap)}")
        unknown = set(plan.depends_on) - known
        if unknown:
            raise ValueError(f"{plan.worker_id} has unknown dependencies: {sorted(unknown)}")
    # Detect dependency cycles with a small DFS.
    visiting: set[str] = set(); visited: set[str] = set()
    by_id = {p.worker_id: p for p in plans}
    def visit(worker_id: str) -> None:
        if worker_id in visiting:
            raise ValueError("worker dependency cycle")
        if worker_id in visited:
            return
        visiting.add(worker_id)
        for dep in by_id[worker_id].depends_on:
            visit(dep)
        visiting.remove(worker_id); visited.add(worker_id)
    for worker_id in ids:
        visit(worker_id)


def plan_from_request(prompt: str, raw_plan: list[dict[str, Any]] | None = None) -> list[WorkerPlan]:
    if raw_plan:
        plans = [WorkerPlan.from_dict(item, i) for i, item in enumerate(raw_plan)]
        validate_plan(plans)
        return plans
    text = str(prompt or "").lower()
    # This is intentionally narrow: arbitrary natural language must not cause
    # an agent to guess destructive edits. It is the real disposable proof.
    if "create a small feature" in text and "test failure" in text:
        plans = [
            WorkerPlan(
                "feature", "create feature", ["feature.py", "test_feature.py"],
                [
                    {"op": "write_file", "path": "feature.py", "content": "def answer():\n    return 41\n"},
                    {"op": "write_file", "path": "test_feature.py", "content": "from feature import answer\n\ndef test_answer():\n    assert answer() == 42\n"},
                ],
                tests=["python -m pytest -q test_feature.py"],
                acceptance=["exists feature.py", "exists test_feature.py"],
                retry_steps=[[{"op": "write_file", "path": "feature.py", "content": "def answer():\n    return 42\n"}]],
            ),
            WorkerPlan(
                "documentation", "add feature documentation", ["FEATURE.md"],
                [{"op": "write_file", "path": "FEATURE.md", "content": "# Feature\n\nThe answer feature is tested.\n"}],
                tests=[], acceptance=["contains FEATURE.md|answer feature"],
            ),
        ]
        validate_plan(plans)
        return plans
    raise ValueError("planner requires an explicit worker plan for this prompt; refusing to guess repository edits")
