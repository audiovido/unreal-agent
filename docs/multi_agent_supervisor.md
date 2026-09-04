# Multi-Agent Supervisor (Task 5 — isolated layer)

Pure-Python, engine-neutral supervisor machinery layered ON TOP of the
existing product (capability registry / mission engine / orchestrator are
untouched).  It is deliberately NOT wired into the live product: this
milestone proves the data model, the deterministic routing and the
dependency-aware scheduling with fake workers only.

Module: `core/supervisor.py` · Tests: `tests/test_supervisor.py` (30).

## Why it exists

The product today drives ONE Unreal shell per task.  Task 5 is the
supervisor-layer foundation for a FUTURE multi-worker deployment (Unreal
worker, asset/Blender worker, UI worker, verifier...) without redesigning
the existing single-worker architecture.  Everything here is a pure
computation over in-memory dataclasses, so the layer is testable and
deterministic by construction — no Unreal, Ollama, Blender, network or
filesystem anywhere in the module or its tests.

## Pieces

### 1. Worker capability registry
`WorkerSpec(name, capabilities, keywords)` declares what a worker can do.
`WorkerRegistry` is ordered — insertion order is the deterministic
tie-break for routing — and rejects duplicate names and empty capability
sets.

### 2. Task decomposition data model
`SubTask(id, capability, description, deps, max_retries)` + `SupervisedPlan`.
`decompose_goal(goal, registry)` matches each worker whose name/keyword
appears in the goal text and emits one subtask for its primary capability,
then appends a single `verify` subtask depending on ALL work subtasks.
Verify-only workers are never matched as work themselves.  A goal that
matches nothing yields an empty plan (overall `NO_WORK`).

### 3. Deterministic task-to-worker routing
`route_subtask(subtask, registry)` picks the FIRST registered worker that
declares the subtask's capability — no randomness, no load heuristics, no
ambiguity.  Returns `None` when no worker owns the capability (subtask
becomes `unroutable`, which is terminal — retrying cannot help).

### 4. Dependency-aware parallel scheduling
`compute_waves(plan)` performs a topological layering: wave 0 is every
subtask without dependencies; each later wave holds subtasks whose
dependencies all live in earlier waves.  Tasks inside one wave are
independent and MAY run in parallel; the executor starts a wave only after
the previous wave fully finished (success or permanent failure).

### 5. Worker status tracking
`WorkerRunState` per worker (`idle` → `running` → `done`, completed/failed
task lists) and `TaskRunState` per subtask
(`pending` → `running` → `succeeded` | `failed` | `unroutable` | `skipped`).
`SupervisedReport` serializes the whole run with `to_dict()`.

### 6. Retry and failure states
Each subtask carries `max_retries` (default 2 → up to 3 bounded attempts).
A failed attempt is recorded with its worker and validation verdict.  When
a dependency fails permanently, dependent subtasks are marked `skipped`
and never executed.  A permanently failed subtask marks the overall run
`FAILED`; full success marks it `SUCCESS`.

### 7. Result validation
`validate_worker_result(subtask, result, expectations)` enforces the
structured-result contract: a worker result must be a dict with a boolean
`ok`; success requires an `evidence` dict whose keys include every key the
caller's expectations table demands for that capability; failure requires
an `error` string.  Validation failures count as failed attempts and retry
bounded.

## Worker protocol

Real integrations attach behind the same protocol the fakes use:

```python
class Worker:
    def execute(self, subtask: SubTask) -> dict:  # {"ok": bool, "evidence": {...}} | {"ok": False, "error": str}
```

`FakeWorker` scripts any capability with a plain callable, so unit tests
cover success, transient failure → retry → success, permanent failure,
unroutable capabilities, missing-evidence failures and expectation gates —
deterministically and instantly.

## Example (happy path)

```python
registry = WorkerRegistry([
    WorkerSpec(name="blueprint", capabilities=["blueprint"], keywords=["blueprint"]),
    WorkerSpec(name="environment", capabilities=["lighting"], keywords=["lighting"]),
    WorkerSpec(name="verifier", capabilities=["verify"], keywords=["verify"]),
])
workers = {"blueprint": FakeWorker("blueprint", ["blueprint"],
                                   {"blueprint": lambda s: {"ok": True, "evidence": {"compiled": True}}}),
           "environment": FakeWorker(...), "verifier": FakeWorker(...)}
report = run_supervised_goal("fix blueprint and lighting", registry, workers)
# waves [["W1", "W2"], ["V3"]] -> report.overall == "SUCCESS"
```

## Limitations (explicit)

- Not wired into `product_core` / `orchestrator` / the packaged runtime —
  this milestone is the isolated supervisor layer plus fake-worker proof.
- Decomposition is keyword-based and deterministic on purpose; an LLM or a
  real capability planner can be swapped in behind the same data model
  without touching the scheduler or executor.
- Workers are assumed single-slot (one subtask at a time); genuine
  multi-process parallelism and live Unreal/Blender adapters are a later
  phase behind the `Worker.execute` protocol.
- No persistence; `SupervisedReport` is the serializable hand-off for a
  future durable supervisor state.
