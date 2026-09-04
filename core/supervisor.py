"""supervisor.py — deterministic multi-agent supervisor layer (Task 5).

Isolated, engine-neutral supervisor machinery layered ON TOP of the existing
product (capability registry, mission engine, orchestrator).  It is a pure
Python planning/execution model for MULTIPLE workers:

  - Worker capability registry   (which worker can do what)
  - Task decomposition           (goal -> capability subtasks + verify)
  - Deterministic routing        (subtask -> the single owning worker)
  - Dependency-aware waves       (parallel waves over the subtask DAG)
  - Worker status tracking       (idle / running / succeeded / failed)
  - Retry + failure states       (bounded attempts, permanent failure)
  - Result validation            (structured ok + evidence expectations)

Design rules:

  * NO live Unreal / Ollama / Blender / network / filesystem.  Every
    function is a pure computation over in-memory dataclasses, so the whole
    layer is testable with fake workers and deterministic by construction.
  * Deterministic: given the same inputs, routing order, wave order and the
    report are identical run to run (no randomness, no wall-clock sleeps).
  * Non-invasive: this module imports nothing from the live-tool stack and
    is NOT wired into product_core / orchestrator.  A later phase can attach
    real executors behind the same Worker.execute(subtask) protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional

# ---------------------------------------------------------------------------
# Status vocabulary
# ---------------------------------------------------------------------------

WORKER_IDLE = "idle"
WORKER_RUNNING = "running"
WORKER_DONE = "done"

SUBTASK_PENDING = "pending"
SUBTASK_RUNNING = "running"
SUBTASK_SUCCEEDED = "succeeded"
SUBTASK_FAILED = "failed"          # permanently after bounded retries
SUBTASK_UNROUTABLE = "unroutable"  # no registered worker has the capability
SUBTASK_SKIPPED = "skipped"        # a dependency failed permanently

OVERALL_SUCCESS = "SUCCESS"
OVERALL_FAILED = "FAILED"
OVERALL_NO_WORK = "NO_WORK"

DEFAULT_MAX_RETRIES = 2  # attempts = 1 + max_retries


# ---------------------------------------------------------------------------
# Worker capability registry
# ---------------------------------------------------------------------------

@dataclass
class WorkerSpec:
    """Declaration of what a worker can execute."""

    name: str
    capabilities: List[str]
    description: str = ""
    keywords: List[str] = field(default_factory=list)  # goal-matching hints

    def __post_init__(self) -> None:
        self.capabilities = list(dict.fromkeys(self.capabilities))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "capabilities": list(self.capabilities),
            "description": self.description,
            "keywords": list(self.keywords),
        }


class WorkerRegistry:
    """Ordered registry of worker capability declarations.

    Insertion order is the deterministic tie-break used by routing, so two
    workers declaring the same capability never produce an ambiguous route.
    """

    def __init__(self, workers: Optional[Iterable[WorkerSpec]] = None) -> None:
        self._specs: Dict[str, WorkerSpec] = {}
        for w in workers or []:
            self.register(w)

    def register(self, spec: WorkerSpec) -> None:
        if not spec.name:
            raise ValueError("worker name must not be empty")
        if spec.name in self._specs:
            raise ValueError(f"duplicate worker name: {spec.name}")
        if not spec.capabilities:
            raise ValueError(f"worker {spec.name} declares no capabilities")
        self._specs[spec.name] = spec

    def get(self, name: str) -> Optional[WorkerSpec]:
        return self._specs.get(name)

    def has(self, name: str) -> bool:
        return name in self._specs

    def workers_for(self, capability: str) -> List[WorkerSpec]:
        """Workers that can execute `capability`, in registration order."""
        return [w for w in self._specs.values()
                if capability in w.capabilities]

    def first_worker_for(self, capability: str) -> Optional[str]:
        for w in self._specs.values():
            if capability in w.capabilities:
                return w.name
        return None

    def all(self) -> Dict[str, WorkerSpec]:
        return dict(self._specs)

    def names(self) -> List[str]:
        return list(self._specs.keys())

    def to_dict(self) -> Dict[str, Any]:
        return {name: spec.to_dict() for name, spec in self._specs.items()}


def build_worker_registry(
    workers: Iterable[WorkerSpec],
) -> WorkerRegistry:
    return WorkerRegistry(workers)


# ---------------------------------------------------------------------------
# Task decomposition data model
# ---------------------------------------------------------------------------

@dataclass
class SubTask:
    """One unit of work, requiring one capability, with explicit deps."""

    id: str
    capability: str
    description: str
    deps: List[str] = field(default_factory=list)  # other SubTask ids
    max_retries: int = DEFAULT_MAX_RETRIES

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "capability": self.capability,
            "description": self.description,
            "deps": list(self.deps),
            "max_retries": self.max_retries,
        }


@dataclass
class SupervisedPlan:
    """A decomposed goal: ordered subtasks plus their dependency edges."""

    goal: str
    subtasks: List[SubTask] = field(default_factory=list)
    waves: List[List[str]] = field(default_factory=list)  # task ids per wave

    def by_id(self, task_id: str) -> Optional[SubTask]:
        for s in self.subtasks:
            if s.id == task_id:
                return s
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "subtasks": [s.to_dict() for s in self.subtasks],
            "waves": [list(w) for w in self.waves],
        }


def decompose_goal(
    goal: str,
    registry: WorkerRegistry,
    *,
    verify_capability: str = "verify",
) -> SupervisedPlan:
    """Deterministically decompose a goal into capability subtasks.

    Each registered worker whose name OR declared keyword appears in the
    lower-cased goal contributes ONE subtask requiring that worker's primary
    capability (its first declared capability) — deterministic, no model,
    no over-emission.  When at least one work subtask exists, a single
    ``verify`` subtask depending on ALL of them is appended.  A goal that
    matches nothing produces an empty plan (overall NO_WORK).
    """
    text = goal.lower()
    work: List[SubTask] = []
    index = 0
    for spec in registry.all().values():
        if not spec.capabilities:
            continue
        primary = spec.capabilities[0]
        if primary == verify_capability:
            # verify-only workers are never matched as WORK; the appended
            # verify subtask below is the single place they run.
            continue
        hints = [spec.name] + list(spec.keywords or [])
        if not any(h.lower() in text for h in hints):
            continue
        index += 1
        work.append(SubTask(
            id=f"W{index}",
            capability=primary,
            description=f"{spec.name} executes {primary}",
        ))
    if work:
        index += 1
        work.append(SubTask(
            id=f"V{index}",
            capability=verify_capability,
            description="verify aggregate result",
            deps=[s.id for s in work],
        ))
    plan = SupervisedPlan(goal=goal, subtasks=work)
    plan.waves = compute_waves(plan)
    return plan


def compute_waves(plan: SupervisedPlan) -> List[List[str]]:
    """Topological waves over the subtask DAG.

    Wave 0 holds every subtask with no deps; each later wave holds subtasks
    whose deps all completed in earlier waves.  Tasks inside one wave are
    independent and MAY run in parallel.  Deterministic: within a wave,
    tasks are ordered by plan order.
    """
    ids = [s.id for s in plan.subtasks]
    level: Dict[str, int] = {}
    for s in plan.subtasks:
        dep_levels = [level[d] for d in s.deps if d in level]
        level[s.id] = (max(dep_levels) + 1) if dep_levels else 0
    max_lv = max(level.values()) if level else -1
    return [[tid for tid in ids if level[tid] == lv]
            for lv in range(max_lv + 1)]


# ---------------------------------------------------------------------------
# Deterministic routing
# ---------------------------------------------------------------------------

def route_subtask(subtask: SubTask, registry: WorkerRegistry) -> Optional[str]:
    """The single owning worker for a subtask.

    First registered worker that declares the subtask's capability wins —
    fully deterministic.  Returns None when no worker can execute it.
    """
    return registry.first_worker_for(subtask.capability)


# ---------------------------------------------------------------------------
# Result validation
# ---------------------------------------------------------------------------

@dataclass
class ValidationOutcome:
    ok: bool
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "reason": self.reason}


def validate_worker_result(
    subtask: SubTask,
    result: Any,
    *,
    expectations: Optional[Dict[str, List[str]]] = None,
) -> ValidationOutcome:
    """Structured result validation.

    A worker result must be a dict with a boolean ``ok``.  When ``ok`` is
    True the dict must carry ``evidence`` (a dict) whose keys include every
    expectation listed for the subtask's capability in ``expectations``.
    When ``ok`` is False it should carry ``error`` text but a missing error
    is reported, not silently accepted.
    """
    if not isinstance(result, dict):
        return ValidationOutcome(False, "result is not a dict")
    ok = result.get("ok")
    if not isinstance(ok, bool):
        return ValidationOutcome(False, "result['ok'] must be a bool")
    if ok:
        evidence = result.get("evidence")
        if not isinstance(evidence, dict):
            return ValidationOutcome(False, "success result needs evidence dict")
        wanted = (expectations or {}).get(subtask.capability) or []
        missing = [k for k in wanted if k not in evidence]
        if missing:
            return ValidationOutcome(
                False, f"evidence missing keys: {sorted(missing)}")
        return ValidationOutcome(True)
    if not result.get("error"):
        return ValidationOutcome(False, "failure result needs an error field")
    return ValidationOutcome(False, str(result.get("error"))[:200])


# ---------------------------------------------------------------------------
# Worker protocol + fake executor
# ---------------------------------------------------------------------------

class Worker:
    """Protocol: an executable worker.

    ``execute(subtask) -> dict`` returns a structured result with ``ok`` and
    either ``evidence`` (dict) or ``error`` (str).  Real integrations attach
    behind this protocol; tests use FakeWorker.
    """

    name: str = ""
    capabilities: List[str] = []

    def execute(self, subtask: SubTask) -> Dict[str, Any]:  # pragma: no cover
        raise NotImplementedError


class FakeWorker(Worker):
    """Deterministic in-memory worker for unit tests and dry runs.

    Each capability maps to a small callable ``fn(subtask) -> dict``, so a
    test can script success, failure, retry-then-success, or per-task
    evidence exactly as needed — no live services.
    """

    def __init__(
        self,
        name: str,
        capabilities: List[str],
        impls: Dict[str, Callable[[SubTask], Dict[str, Any]]],
        *,
        keywords: Optional[List[str]] = None,
    ) -> None:
        self.name = name
        self.capabilities = list(capabilities)
        self.impls = dict(impls)
        self.keywords = list(keywords or [])
        self.calls: List[str] = []

    def execute(self, subtask: SubTask) -> Dict[str, Any]:
        self.calls.append(subtask.id)
        impl = self.impls.get(subtask.capability)
        if impl is None:
            return {"ok": False,
                    "error": f"{self.name} cannot execute {subtask.capability}"}
        return impl(subtask)

    def to_spec(self) -> WorkerSpec:
        return WorkerSpec(name=self.name, capabilities=self.capabilities,
                          description="fake worker", keywords=self.keywords)


# ---------------------------------------------------------------------------
# Worker status tracking
# ---------------------------------------------------------------------------

@dataclass
class WorkerRunState:
    """Live status of one worker during a supervised run."""

    name: str
    status: str = WORKER_IDLE
    current_subtask: Optional[str] = None
    completed: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    task_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "current_subtask": self.current_subtask,
            "completed": list(self.completed),
            "failed": list(self.failed),
        }


@dataclass
class TaskAttempt:
    """One execution attempt of a subtask."""

    worker: str
    result: Dict[str, Any] = field(default_factory=dict)
    validated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {"worker": self.worker,
                "validated": self.validated,
                "result": dict(self.result)}


@dataclass
class TaskRunState:
    """Live status of one subtask during a supervised run."""

    id: str
    status: str = SUBTASK_PENDING
    worker: Optional[str] = None
    attempts: List[TaskAttempt] = field(default_factory=list)
    final_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "worker": self.worker,
            "attempts": [a.to_dict() for a in self.attempts],
            "final_reason": self.final_reason,
        }


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

@dataclass
class SupervisedReport:
    goal: str
    overall: str = OVERALL_NO_WORK
    tasks: Dict[str, TaskRunState] = field(default_factory=dict)
    workers: Dict[str, WorkerRunState] = field(default_factory=dict)
    waves_executed: List[List[str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "overall": self.overall,
            "tasks": {k: v.to_dict() for k, v in self.tasks.items()},
            "workers": {k: v.to_dict() for k, v in self.workers.items()},
            "waves_executed": [list(w) for w in self.waves_executed],
        }


class SupervisorExecutor:
    """Deterministic dependency-aware multi-worker executor.

    Executes a SupervisedPlan: routes every subtask to its owning worker,
    runs wave by wave (a wave starts only when every earlier wave finished),
    validates each result, retries bounded per subtask, and never starts a
    subtask whose dependencies failed permanently (it is marked skipped).
    """

    def __init__(
        self,
        registry: WorkerRegistry,
        workers: Dict[str, Worker],
        *,
        expectations: Optional[Dict[str, List[str]]] = None,
        route_fn: Callable[[SubTask, WorkerRegistry], Optional[str]] = route_subtask,
    ) -> None:
        self.registry = registry
        self.workers = workers
        self.expectations = expectations or {}
        self.route_fn = route_fn

    def _validate(self, subtask: SubTask, result: Any) -> ValidationOutcome:
        return validate_worker_result(subtask, result,
                                      expectations=self.expectations)

    # -- one execution attempt ----------------------------------------------
    def _attempt(self, subtask: SubTask, state: TaskRunState) -> bool:
        worker_name = self.route_fn(subtask, self.registry)
        if worker_name is None or worker_name not in self.workers:
            state.status = SUBTASK_UNROUTABLE
            state.final_reason = (
                f"no executable worker for capability '{subtask.capability}'")
            return False
        worker = self.workers[worker_name]
        state.worker = worker_name
        wstate = self.workers_state[worker_name]
        wstate.status = WORKER_RUNNING
        wstate.current_subtask = subtask.id
        result = worker.execute(subtask)  # may raise for a broken worker
        verdict = self._validate(subtask, result)
        state.attempts.append(TaskAttempt(worker=worker_name,
                                          result=dict(result or {}),
                                          validated=verdict.ok))
        wstate.current_subtask = None
        if verdict.ok:
            wstate.status = WORKER_DONE
            wstate.completed.append(subtask.id)
            state.status = SUBTASK_SUCCEEDED
            return True
        wstate.failed.append(subtask.id)
        wstate.status = WORKER_DONE
        state.final_reason = verdict.reason or "validation failed"
        return False

    def _run_subtask(self, subtask: SubTask, state: TaskRunState) -> None:
        """Bounded retries; a permanently failed dep skips the subtask."""
        for dep_id in subtask.deps:
            dep = self.task_states[dep_id]
            if dep.status in (SUBTASK_FAILED, SUBTASK_UNROUTABLE):
                state.status = SUBTASK_SKIPPED
                state.final_reason = f"dependency {dep_id} failed"
                return
        max_attempts = 1 + max(0, subtask.max_retries)
        for _ in range(max_attempts):
            state.status = SUBTASK_RUNNING
            if self._attempt(subtask, state):
                return
            if state.status == SUBTASK_UNROUTABLE:
                return  # no owner exists - retrying cannot help
        state.status = SUBTASK_FAILED

    # -- whole-plan run -----------------------------------------------------
    def run(self, plan: SupervisedPlan) -> SupervisedReport:
        report = SupervisedReport(goal=plan.goal)
        if not plan.subtasks:
            return report  # overall stays NO_WORK

        # Worker registry tracks capability declarations; run state is per
        # worker across the whole plan.
        self.task_states = {
            s.id: TaskRunState(id=s.id) for s in plan.subtasks}
        self.workers_state = {}
        for w in self.workers.values():
            names = self.registry.workers_for(w.capabilities[0]) \
                if w.capabilities else []
            owner = next((x.name for x in names if x.name == w.name), w.name)
            self.workers_state[owner] = WorkerRunState(name=owner)
        report.tasks = self.task_states
        report.workers = self.workers_state

        for wave in plan.waves:
            executed: List[str] = []
            for tid in wave:
                subtask = plan.by_id(tid)
                if subtask is None:
                    continue
                state = self.task_states[tid]
                self._run_subtask(subtask, state)
                executed.append(tid)
            report.waves_executed.append(executed)

        statuses = [s.status for s in self.task_states.values()]
        if all(s == SUBTASK_SUCCEEDED for s in statuses):
            report.overall = OVERALL_SUCCESS
        else:
            report.overall = OVERALL_FAILED
        return report


def run_supervised_goal(
    goal: str,
    registry: WorkerRegistry,
    workers: Dict[str, Worker],
    *,
    expectations: Optional[Dict[str, List[str]]] = None,
    verify_capability: str = "verify",
    executor_cls: Callable[..., SupervisorExecutor] = SupervisorExecutor,
) -> SupervisedReport:
    """One-shot convenience: decompose -> route -> schedule -> run."""
    plan = decompose_goal(goal, registry, verify_capability=verify_capability)
    executor = executor_cls(registry, workers, expectations=expectations)
    return executor.run(plan)
