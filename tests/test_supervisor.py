"""AIVIDO TASK 5 — multi-agent supervisor unit tests.

Pure fake-worker tests: no Unreal, no Ollama, no Blender, no network, no
filesystem.  Everything is deterministic in-memory, so the assertions cover
registry order, wave shape, routing tie-breaks, retries, failure states and
validation exactly.
"""
from __future__ import annotations

import pytest

from core.supervisor import (
    FakeWorker,
    OVERALL_FAILED,
    OVERALL_NO_WORK,
    OVERALL_SUCCESS,
    SUBTASK_FAILED,
    SUBTASK_PENDING,
    SUBTASK_RUNNING,
    SUBTASK_SKIPPED,
    SUBTASK_SUCCEEDED,
    SUBTASK_UNROUTABLE,
    WorkerRegistry,
    WorkerSpec,
    SupervisorExecutor,
    SubTask,
    SupervisedPlan,
    WorkerRunState,
    TaskRunState,
    compute_waves,
    decompose_goal,
    route_subtask,
    run_supervised_goal,
    validate_worker_result,
)


# ---------------------------------------------------------------------------
# Fixtures: a small deterministic multi-worker fleet
# ---------------------------------------------------------------------------

def _ok(**extra):
    return {"ok": True, "evidence": {"done": True, **extra}}


def _fail(reason="boom"):
    return {"ok": False, "error": reason}


@pytest.fixture()
def fleet():
    """blueprint + environment workers plus an explicit verifier."""
    registry = WorkerRegistry([
        WorkerSpec(name="blueprint", capabilities=["blueprint"],
                   keywords=["blueprint", "graph"]),
        WorkerSpec(name="environment", capabilities=["lighting"],
                   keywords=["lighting", "light", "material"]),
        WorkerSpec(name="verifier", capabilities=["verify"],
                   keywords=["verify"]),
    ])
    workers = {
        "blueprint": FakeWorker("blueprint", ["blueprint"],
                                {"blueprint": lambda s: _ok(compiled=True)},
                                keywords=["blueprint", "graph"]),
        "environment": FakeWorker("environment", ["lighting"],
                                  {"lighting": lambda s: _ok(light=True)},
                                  keywords=["lighting", "light"]),
        "verifier": FakeWorker("verifier", ["verify"],
                               {"verify": lambda s: _ok(verified=True)},
                               keywords=["verify"]),
    }
    return registry, workers


# ===========================================================================
# Worker capability registry
# ===========================================================================

class TestWorkerRegistry:
    def test_register_and_get(self):
        reg = WorkerRegistry()
        reg.register(WorkerSpec(name="a", capabilities=["x"]))
        assert reg.has("a")
        assert reg.get("a").capabilities == ["x"]
        assert reg.names() == ["a"]

    def test_duplicate_name_rejected(self):
        reg = WorkerRegistry([WorkerSpec(name="a", capabilities=["x"])])
        with pytest.raises(ValueError):
            reg.register(WorkerSpec(name="a", capabilities=["y"]))

    def test_empty_capabilities_rejected(self):
        with pytest.raises(ValueError):
            WorkerRegistry([WorkerSpec(name="a", capabilities=[])])

    def test_capabilities_deduplicated_and_stable(self):
        spec = WorkerSpec(name="a", capabilities=["x", "y", "x"])
        assert spec.capabilities == ["x", "y"]

    def test_workers_for_preserves_registration_order(self):
        reg = WorkerRegistry([
            WorkerSpec(name="first", capabilities=["x"]),
            WorkerSpec(name="second", capabilities=["x", "y"]),
        ])
        assert [w.name for w in reg.workers_for("x")] == ["first", "second"]
        assert reg.first_worker_for("x") == "first"  # deterministic tie-break
        assert reg.first_worker_for("missing") is None

    def test_to_dict_round_trip(self):
        reg = WorkerRegistry([WorkerSpec(name="a", capabilities=["x"],
                                         keywords=["k"])])
        d = reg.to_dict()
        assert d["a"]["capabilities"] == ["x"]


# ===========================================================================
# Task decomposition data model
# ===========================================================================

class TestDecomposition:
    def test_goal_matches_workers_into_subtasks_plus_verify(self, fleet):
        registry, _ = fleet
        plan = decompose_goal("fix blueprint and lighting in the level",
                              registry)
        caps = [(s.capability, s.deps) for s in plan.subtasks]
        # blueprint worker (name) + environment worker (lighting keyword) +
        # one verify depending on both
        assert caps == [("blueprint", []), ("lighting", []),
                        ("verify", ["W1", "W2"])]

    def test_waves_fork_then_verify(self, fleet):
        registry, _ = fleet
        plan = decompose_goal("fix blueprint and lighting", registry)
        assert plan.waves == [["W1", "W2"], ["V3"]]

    def test_unmatched_goal_gives_empty_plan(self, fleet):
        registry, _ = fleet
        plan = decompose_goal("make me a sandwich", registry)
        assert plan.subtasks == []
        assert plan.waves == []

    def test_verify_only_worker_never_becomes_work(self, fleet):
        registry, _ = fleet
        # verify-only workers are the appended V-subtask, never a W-subtask;
        # a goal that mentions nothing but verify has no work to verify.
        plan = decompose_goal("verify the scene please", registry)
        assert plan.subtasks == []
        # with real work present the appended verify still routes to verifier
        plan2 = decompose_goal("add blueprint graphs", registry)
        assert [s.capability for s in plan2.subtasks] == ["blueprint", "verify"]
    def test_manual_plan_chain_waves(self):
        plan = SupervisedPlan(goal="chain", subtasks=[
            SubTask(id="A", capability="x", description="a"),
            SubTask(id="B", capability="x", description="b", deps=["A"]),
            SubTask(id="C", capability="x", description="c", deps=["B"]),
        ])
        plan.waves = compute_waves(plan)
        assert plan.waves == [["A"], ["B"], ["C"]]

    def test_manual_plan_fork_join_waves(self):
        plan = SupervisedPlan(goal="fork", subtasks=[
            SubTask(id="A", capability="x", description="a"),
            SubTask(id="B", capability="x", description="b"),
            SubTask(id="C", capability="x", description="c",
                    deps=["A", "B"]),
        ])
        plan.waves = compute_waves(plan)
        assert plan.waves == [["A", "B"], ["C"]]


# ===========================================================================
# Deterministic routing
# ===========================================================================

class TestRouting:
    def test_first_registered_worker_wins(self, fleet):
        registry, _ = fleet
        sub = SubTask(id="S1", capability="lighting", description="light")
        assert route_subtask(sub, registry) == "environment"

    def test_unroutable_capability_returns_none(self, fleet):
        registry, _ = fleet
        sub = SubTask(id="S1", capability="cinematics", description="cine")
        assert route_subtask(sub, registry) is None


# ===========================================================================
# Result validation
# ===========================================================================

class TestValidation:
    def test_success_needs_bool_ok_and_evidence_dict(self):
        sub = SubTask(id="S", capability="x", description="x")
        assert validate_worker_result(sub, {"ok": True,
                                            "evidence": {"a": 1}}).ok
        assert not validate_worker_result(sub, {"ok": True}).ok
        assert not validate_worker_result(sub, {"ok": "yes",
                                                "evidence": {}}).ok
        assert not validate_worker_result(sub, "not a dict").ok

    def test_failure_needs_error_field(self):
        sub = SubTask(id="S", capability="x", description="x")
        assert not validate_worker_result(sub, {"ok": False}).ok
        assert not validate_worker_result(
            sub, {"ok": False, "error": "boom"}).ok  # ok:False -> invalid
        # (failure results are 'valid' in shape but fail the gate)

    def test_expectations_require_evidence_keys(self):
        sub = SubTask(id="S", capability="blueprint", description="bp")
        exp = {"blueprint": ["compiled"]}
        assert validate_worker_result(
            sub, {"ok": True, "evidence": {"compiled": True}},
            expectations=exp).ok
        out = validate_worker_result(
            sub, {"ok": True, "evidence": {"saved": True}},
            expectations=exp)
        assert not out.ok and "compiled" in out.reason


# ===========================================================================
# Executor: happy path + waves
# ===========================================================================

class TestExecutorHappyPath:
    def test_fork_join_success(self, fleet):
        registry, workers = fleet
        report = run_supervised_goal("fix blueprint and lighting", registry,
                                     workers)
        assert report.overall == OVERALL_SUCCESS
        assert list(report.waves_executed) == [["W1", "W2"], ["V3"]]
        for state in report.tasks.values():
            assert state.status == SUBTASK_SUCCEEDED
            assert state.worker is not None
            assert state.attempts and state.attempts[-1].validated

    def test_workers_reached_in_parallel_wave(self, fleet):
        registry, workers = fleet
        calls = {"blueprint": [], "environment": [], "verifier": []}
        for w in workers.values():
            w.calls.clear()
        report = run_supervised_goal("fix blueprint and lighting", registry,
                                     workers)
        # wave 0 ran before wave 1: verifier (V3) called last
        assert workers["verifier"].calls == ["V3"]
        assert sorted(workers["blueprint"].calls + workers["environment"].calls) \
            == ["W1", "W2"]
        assert report.overall == OVERALL_SUCCESS

    def test_worker_run_state_transitions(self, fleet):
        registry, workers = fleet
        executor = SupervisorExecutor(registry, workers)
        plan = decompose_goal("fix blueprint and lighting", registry)
        executor.run(plan)
        env = executor.workers_state["environment"]
        from core.supervisor import WORKER_DONE
        assert env.status == WORKER_DONE
        assert env.completed == ["W2"]
        assert env.failed == []
        verifier = executor.workers_state["verifier"]
        assert verifier.completed == ["V3"]

    def test_no_work_goal(self, fleet):
        registry, workers = fleet
        report = run_supervised_goal("make me a sandwich", registry, workers)
        assert report.overall == OVERALL_NO_WORK
        assert report.tasks == {}


# ===========================================================================
# Executor: retry + failure states
# ===========================================================================

class TestRetriesAndFailures:
    def test_retry_then_success(self):
        # the fleet worker owns x AND verify, so the appended verify subtask
        # routes back to it and the whole goal can succeed
        registry = WorkerRegistry(
            [WorkerSpec(name="w", capabilities=["x", "verify"])])
        attempts = {"n": 0}

        def flaky(_sub):
            attempts["n"] += 1
            if attempts["n"] < 3:
                return _fail("transient")
            return _ok()

        workers = {"w": FakeWorker(
            "w", ["x", "verify"], {"x": flaky,
                                   "verify": lambda s: _ok(verified=True)})}
        report = run_supervised_goal("w", registry, workers)
        assert report.overall == OVERALL_SUCCESS
        state = report.tasks["W1"]
        assert state.status == SUBTASK_SUCCEEDED
        assert len(state.attempts) == 3  # two retries
        assert attempts["n"] == 3

    def test_permanent_failure_marks_dependents_skipped(self):
        registry = WorkerRegistry([
            WorkerSpec(name="bad", capabilities=["x"]),
            WorkerSpec(name="verifier", capabilities=["verify"],
                       keywords=["verify"]),
        ])
        # goal mentions both "bad" and "verify" via keyword -> W1(x) + V2
        workers = {
            "bad": FakeWorker("bad", ["x"], {"x": lambda s: _fail("hard")},
                              keywords=["bad"]),
            "verifier": FakeWorker(
                "verifier", ["verify"],
                {"verify": lambda s: _ok(verified=True)},
                keywords=["verify"]),
        }
        plan = decompose_goal("do bad things then verify", registry)
        assert [s.capability for s in plan.subtasks] == ["x", "verify"]
        report = SupervisorExecutor(registry, workers).run(plan)
        assert report.overall == OVERALL_FAILED
        assert report.tasks["W1"].status == SUBTASK_FAILED
        # verify never ran because its dependency failed permanently
        assert report.tasks["V2"].status == SUBTASK_SKIPPED
        assert workers["verifier"].calls == []

    def test_retry_exhaustion_records_attempts(self):
        registry = WorkerRegistry([WorkerSpec(name="w", capabilities=["x"])])
        workers = {"w": FakeWorker("w", ["x"], {"x": lambda s: _fail("nope")})}
        report = run_supervised_goal("w", registry, workers)
        state = report.tasks["W1"]
        assert state.status == SUBTASK_FAILED
        from core.supervisor import DEFAULT_MAX_RETRIES
        # default max_retries=2 -> exactly 1 + 2 = 3 bounded attempts
        assert len(state.attempts) == 1 + DEFAULT_MAX_RETRIES
        assert state.final_reason
    def test_max_retries_zero_fails_fast(self):
        def always_fail(_sub):
            return _fail("no")
        registry = WorkerRegistry([WorkerSpec(name="w", capabilities=["x"])])
        plan = SupervisedPlan(goal="g", subtasks=[
            SubTask(id="S1", capability="x", description="x",
                    max_retries=0)])
        plan.waves = compute_waves(plan)
        workers = {"w": FakeWorker("w", ["x"], {"x": always_fail})}
        report = SupervisorExecutor(registry, workers).run(plan)
        assert report.tasks["S1"].status == SUBTASK_FAILED
        assert len(report.tasks["S1"].attempts) == 1

    def test_unroutable_capability(self):
        registry = WorkerRegistry([WorkerSpec(name="w", capabilities=["x"])])
        plan = SupervisedPlan(goal="g", subtasks=[
            SubTask(id="S1", capability="no_such_cap", description="z")])
        plan.waves = compute_waves(plan)
        workers = {"w": FakeWorker("w", ["x"], {"x": lambda s: _ok()})}
        report = SupervisorExecutor(registry, workers).run(plan)
        assert report.tasks["S1"].status == SUBTASK_UNROUTABLE
        assert report.overall == OVERALL_FAILED


# ===========================================================================
# Executor: validation enforcement
# ===========================================================================

class TestValidationInRun:
    def test_missing_evidence_is_retried_and_fails(self):
        registry = WorkerRegistry([WorkerSpec(name="w", capabilities=["x"])])

        def bad_ok(_sub):
            return {"ok": True}  # violates evidence contract

        workers = {"w": FakeWorker("w", ["x"], {"x": bad_ok})}
        report = run_supervised_goal("w", registry, workers)
        assert report.overall == OVERALL_FAILED
        state = report.tasks["W1"]
        assert state.status == SUBTASK_FAILED
        assert len(state.attempts) == 3  # every attempt failed validation
        assert all(not a.validated for a in state.attempts)

    def test_expectations_gate_success(self):
        registry = WorkerRegistry([
            WorkerSpec(name="bp", capabilities=["blueprint"],
                       keywords=["blueprint"]),
            WorkerSpec(name="verifier", capabilities=["verify"],
                       keywords=["verify"]),
        ])
        workers = {
            "bp": FakeWorker("bp", ["blueprint"],
                             {"blueprint": lambda s: _ok(compiled=True)},
                             keywords=["blueprint"]),
            "verifier": FakeWorker(
                "verifier", ["verify"],
                {"verify": lambda s: _ok(verified=True)},
                keywords=["verify"]),
        }
        # without the expectation the run succeeds...
        ok_run = run_supervised_goal("build blueprint then verify", registry,
                                     workers)
        assert ok_run.overall == OVERALL_SUCCESS
        # ...with the expectation it fails because evidence lacks the key
        workers["bp"].calls.clear()
        bad_run = SupervisorExecutor(
            registry, workers,
            expectations={"blueprint": ["compiled", "saved"]}).run(
            decompose_goal("build blueprint then verify", registry))
        assert bad_run.overall == OVERALL_FAILED
        assert bad_run.tasks["W1"].status == SUBTASK_FAILED


# ===========================================================================
# Determinism
# ===========================================================================

class TestDeterminism:
    def test_same_inputs_produce_identical_reports(self, fleet):
        registry, workers = fleet
        a = run_supervised_goal("fix blueprint and lighting", registry,
                                workers).to_dict()
        b = run_supervised_goal("fix blueprint and lighting", registry,
                                workers).to_dict()
        assert a == b

    def test_wave_order_and_routing_are_stable(self, fleet):
        registry, workers = fleet
        plan = decompose_goal("lighting issues", registry)
        # 'lighting' -> environment worker (its keyword), W1 lighting only
        assert [s.capability for s in plan.subtasks] == ["lighting", "verify"]
        assert plan.waves == [["W1"], ["V2"]]
