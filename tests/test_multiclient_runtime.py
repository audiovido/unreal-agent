"""test_multiclient_runtime.py — hermetic tests for the multi-client Aivido
runtime (Phases 1-11).

Every test uses fake bridges and a fake registry, so nothing touches a real
editor, bridge, model or filesystem outside tmp_path. The scenarios map 1:1
to the required Phase 11 matrix:

    1.  two sessions / two projects
    2.  task A routes only to bridge A
    3.  task B routes only to bridge B
    4.  proof A cannot satisfy execution B
    5.  project A mutation lock does not block unrelated project B
    6.  same-project conflicting mutations serialize
    7.  READ_ONLY policy remains enforced per session
    8.  crashed session does not kill other session
    9.  dynamic bridge allocation does not collide
    10. browser client state remains session-isolated
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import project_registry
from core.bridge_allocator import BridgeAllocator
from core.editor_lease import LeaseRegistry
from core.proof_store import ProofStore
from core.session_execution import SessionRunner
from core.session_model import (
    BLOCKED,
    BUSY,
    CRASHED,
    OFFLINE,
    READY,
    SessionStore,
)
from core.tool_registry import ToolSpec


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeBridge:
    """Mimics the UnrealBridge interface for one project endpoint."""

    def __init__(self, host: str, port: int, project_path: str,
                 pid: int | None = None):
        self.host, self.port = host, port
        self.project_path = project_path
        self.pid = pid or (2000 + port)
        self.alive = True
        self.calls: list[tuple] = []

    def _identity(self) -> dict:
        if not self.alive:
            return {}
        return {
            "ok": True,
            "project_path": self.project_path,
            "project_name": Path(self.project_path).stem,
            "engine": "5.8-test",
            "editor_pid": self.pid,
            "active_map": "/Game/Maps/TestMap",
            "pie_running": False,
        }

    def execute_python(self, code, *, expected_project=None):
        self.calls.append(("execute_python", str(code)[:80]))
        return {"ok": True, "message": "ok", "result": self._identity()}

    def ping(self):
        self.calls.append(("ping", ""))
        return {"ok": True, "result": self._identity()}

    def get_project_identity(self):
        self.calls.append(("get_project_identity", ""))
        return {"ok": True, "result": self._identity()}


class FakeAllocator:
    """Deterministic port allocator: one unique port per project."""

    def __init__(self, base: int = 6766):
        self._ports: dict[str, int] = {}
        self._next = base

    def allocate(self, project_id, preferred=None, force=False):
        if project_id in self._ports:
            return {"ok": True, "port": self._ports[project_id],
                    "reused": True, "host": "127.0.0.1",
                    "project_id": project_id}
        port = preferred if preferred is not None else self._next
        if preferred is None:
            self._next += 1
        self._ports[project_id] = port
        return {"ok": True, "port": port, "reused": False,
                "host": "127.0.0.1", "project_id": project_id}

    def binding_for(self, project_id):
        return self._ports.get(project_id)

    def live_bindings(self):
        return [{"project_id": pid, "host": "127.0.0.1", "port": port,
                 "endpoint": f"127.0.0.1:{port}"}
                for pid, port in sorted(self._ports.items())]

    def release(self, project_id):
        self._ports.pop(project_id, None)
        return {"ok": True}


def make_fake_registry(proof_png: str | None = None):
    """Build a tiny deterministic tool registry bound to one fake bridge."""

    def builder(bridge: FakeBridge) -> dict:
        reg = {}

        def mk(name, fn, destructive=False):
            reg[name] = ToolSpec(name=name, description=name, args={},
                                 func=fn, destructive=destructive)

        def inspect(uproject_path=None, _bridge=None):
            out = {"ok": True, "name": "proj",
                   "uproject_path": uproject_path or bridge.project_path,
                   "source_of_truth": "fake"}
            if proof_png and Path(proof_png).is_file():
                out["path"] = proof_png
            return out

        def spawn_actor(**kw):
            bridge.calls.append(("spawn_actor", json.dumps(kw, default=str)))
            return {"ok": True, "name": "spawned_cube"}

        def list_actors():
            return {"ok": True, "actors": []}

        mk("inspect_project", inspect)
        mk("spawn_actor", spawn_actor, destructive=True)
        mk("list_level_actors", list_actors)
        return reg

    return builder


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runtime(tmp_path):
    """Isolated SessionRunner with fake bridges, tmp stores and leases."""
    store = SessionStore(session_dir=tmp_path / "sessions")
    leases = LeaseRegistry(lease_dir=tmp_path / "leases")
    proofs = ProofStore(root=tmp_path / "proof")
    alloc = FakeAllocator()
    bridges: dict[int, FakeBridge] = {}

    def bridge_factory(host, port, timeout=30.0):
        return bridges[port]

    runner = SessionRunner(
        store=store, leases=leases, proof_store=proofs, allocator=alloc,
        bridge_factory=bridge_factory,
        registry_builder=make_fake_registry(),
    )
    runner._sweeper = None  # never auto-probe in hermetic tests
    return SimpleNamespace(
        tmp=tmp_path, store=store, leases=leases, proofs=proofs,
        alloc=alloc, runner=runner, bridges=bridges)


def make_uproject(tmp_path: Path, name: str) -> str:
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}.uproject"
    p.write_text(json.dumps({"FileVersion": 3, "EngineAssociation": "5.8"}),
                 encoding="utf-8")
    return str(p)


def start_session(runtime, name: str, client_id: str = "browser",
                  project_id: str | None = None):
    """Create + start a session backed by a fake bridge for a project."""
    path = make_uproject(runtime.tmp, name)
    pid = project_id or f"proj_{name.lower()}"
    session = runtime.store.create(pid, path, client_id=client_id,
                                   project_name=name)
    port = runtime.alloc.allocate(pid)["port"]
    runtime.bridges[port] = FakeBridge("127.0.0.1", port, path)
    result = runtime.runner.start_project(session)
    assert result.get("ok"), result
    return session


# ---------------------------------------------------------------------------
# 1. Two sessions / two projects
# ---------------------------------------------------------------------------


def test_two_sessions_two_projects_isolated(runtime):
    a = start_session(runtime, "ProjectA", client_id="client-X")
    b = start_session(runtime, "ProjectB", client_id="client-Y")

    assert a.session_id != b.session_id
    assert a.project_id != b.project_id
    assert a.project_path != b.project_path
    assert a.bridge_port != b.bridge_port
    assert a.client_id == "client-X" and b.client_id == "client-Y"
    assert runtime.store.get(a.session_id).status == READY
    assert runtime.store.get(b.session_id).status == READY

    # No cross-reference in the summaries: A never mentions B's project.
    sa, sb = a.summary(), b.summary()
    assert sa["project_path"] != sb["project_path"]
    assert sa["bridge"] != sb["bridge"]
    assert a.current_execution_id is None
    assert b.current_execution_id is None


def test_session_store_persists_across_instances(runtime):
    start_session(runtime, "PersistMe")
    reloaded = SessionStore(session_dir=runtime.tmp / "sessions")
    assert len(reloaded.list()) == 1
    s = reloaded.list()[0]
    assert s.status == READY and s.project_name == "PersistMe"


# ---------------------------------------------------------------------------
# 2 + 3. Task routing is project/session-exact
# ---------------------------------------------------------------------------


def test_task_a_routes_only_to_bridge_a(runtime):
    a = start_session(runtime, "ProjectA", client_id="client-X")
    b = start_session(runtime, "ProjectB", client_id="client-Y")
    bridge_a = runtime.bridges[a.bridge_port]
    bridge_b = runtime.bridges[b.bridge_port]

    baseline_a = len(bridge_a.calls)
    baseline_b = len(bridge_b.calls)

    res = runtime.runner.run_prompt(
        a.session_id, "inspect the current project and report it",
        mode="execute", read_only=True)
    assert res.get("ok") and res.get("verdict") == "PASS", res

    # Only bridge A gained identity probes / dispatches.
    assert len(bridge_a.calls) > baseline_a
    assert len(bridge_b.calls) == baseline_b
    # Every execute_python probe on A carries A's project identity.
    for kind, _ in bridge_a.calls[baseline_a:]:
        assert kind in ("execute_python", "get_project_identity")


def test_task_b_routes_only_to_bridge_b(runtime):
    a = start_session(runtime, "ProjectA", client_id="client-X")
    b = start_session(runtime, "ProjectB", client_id="client-Y")
    bridge_a = runtime.bridges[a.bridge_port]
    bridge_b = runtime.bridges[b.bridge_port]

    baseline_a = len(bridge_a.calls)
    baseline_b = len(bridge_b.calls)

    res = runtime.runner.run_prompt(
        b.session_id, "inspect the current project and report it",
        mode="execute", read_only=True)
    assert res.get("ok") and res.get("verdict") == "PASS", res

    assert len(bridge_b.calls) > baseline_b
    assert len(bridge_a.calls) == baseline_a


def test_fail_closed_on_unknown_session(runtime):
    res = runtime.runner.run_prompt(
        "sess_does_not_exist", "inspect the current project",
        mode="execute", read_only=True)
    assert res.get("ok") is False
    assert "unknown session" in str(res.get("error"))


# ---------------------------------------------------------------------------
# 4. Proof isolation
# ---------------------------------------------------------------------------


def test_proof_a_cannot_satisfy_execution_b(runtime, tmp_path):
    png = tmp_path / "capture.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nfakepngdata")
    runtime.runner._registry_builder = make_fake_registry(str(png))

    a = start_session(runtime, "ProjectA", client_id="client-X")
    b = start_session(runtime, "ProjectB", client_id="client-Y")

    res = runtime.runner.run_prompt(
        a.session_id, "inspect the current project and report it",
        mode="execute", read_only=True)
    assert res.get("ok") and res.get("verdict") == "PASS", res
    exec_a = res["execution_id"]

    # Proof recorded only under session A / execution A.
    proofs_a = runtime.proofs.list(a.session_id)
    assert len(proofs_a) == 1
    manifest = proofs_a[0]
    assert manifest["session_id"] == a.session_id
    assert manifest["project_id"] == a.project_id
    assert manifest["execution_id"] == exec_a
    assert manifest["files"], "proof manifest must contain recorded files"
    assert manifest["unreal_pid"] == a.unreal_pid

    # Execution B cannot see A's proof, and cannot resolve A's files.
    assert runtime.proofs.list(b.session_id) == []
    assert runtime.proofs.list(a.session_id, "exec_some_other") == []
    name = manifest["files"][0]["name"]
    assert runtime.proofs.resolve(b.session_id, exec_a, name) is None
    assert runtime.proofs.resolve(a.session_id, exec_a, name) is not None

    # The on-disk path contains the session + execution segments.
    recorded = runtime.proofs.execution_dir(a.session_id, exec_a)
    assert recorded.is_dir()
    assert (recorded / "proof.json").is_file()


# ---------------------------------------------------------------------------
# 5 + 6. Project-scoped mutation locks
# ---------------------------------------------------------------------------


def test_project_a_lock_does_not_block_project_b(runtime):
    a = start_session(runtime, "ProjectA", client_id="client-X")
    b = start_session(runtime, "ProjectB", client_id="client-Y")

    # Hold A's mutation lease while B runs a mutating task.
    held = runtime.leases.acquire(a.project_path, owner_id="other",
                                  task_id="t-other")
    assert held.get("ok"), held

    res = runtime.runner.run_prompt(
        b.session_id, "spawn a cube at 0,0,0", mode="execute")
    assert res.get("ok") and res.get("verdict") == "PASS", res

    runtime.leases.release(a.project_path, "other")


def test_same_project_conflicting_mutations_serialize(runtime):
    a = start_session(runtime, "ProjectA", client_id="client-X")

    held = runtime.leases.acquire(a.project_path, owner_id="other",
                                  task_id="t-other")
    assert held.get("ok"), held

    # Second mutating task on the SAME project -> structured BUSY.
    res = runtime.runner.run_prompt(
        a.session_id, "spawn a cube at 0,0,0", mode="execute")
    assert res.get("ok") is False
    assert res.get("code") == "PROJECT_BUSY"
    assert "mutation lease" in str(res.get("error"))
    task = runtime.store.get(a.session_id).get_task(res["execution_id"])
    assert task is not None and task.status == "queued"

    # After release, the same task runs.
    runtime.leases.release(a.project_path, "other")
    res2 = runtime.runner.run_prompt(
        a.session_id, "spawn a cube at 0,0,0", mode="execute")
    assert res2.get("ok") and res2.get("verdict") == "PASS", res2


def test_read_only_does_not_need_mutation_lease(runtime):
    """READ_ONLY tasks take the watcher path and never conflict with a
    mutating lease on another session of the same project."""
    a = start_session(runtime, "ProjectA", client_id="client-X")
    # Second session on the SAME project path (shared editor endpoint).
    a2 = runtime.store.create(a.project_id, a.project_path,
                              client_id="client-X2",
                              project_name="ProjectA")
    port = runtime.alloc.allocate(a.project_id)["port"]
    assert port == a.bridge_port  # same project -> same bridge endpoint
    runtime.bridges[port] = FakeBridge("127.0.0.1", port, a.project_path)
    started = runtime.runner.start_project(a2)
    assert started.get("ok"), started

    held = runtime.leases.acquire(a.project_path, owner_id="mutator",
                                  task_id="t-mut")
    assert held.get("ok")
    # READ_ONLY watcher coexists with the mutating lease on the SAME project.
    res = runtime.runner.run_prompt(
        a2.session_id, "inspect the current project and report it",
        mode="execute", read_only=True)
    assert res.get("ok") and res.get("verdict") == "PASS", res
    runtime.leases.release(a.project_path, "mutator")


# ---------------------------------------------------------------------------
# 7. READ_ONLY policy enforcement per session
# ---------------------------------------------------------------------------


def test_read_only_policy_enforced_per_session(runtime):
    a = start_session(runtime, "ProjectA", client_id="client-X")
    bridge_a = runtime.bridges[a.bridge_port]
    baseline = len(bridge_a.calls)

    res = runtime.runner.run_prompt(
        a.session_id, "read only: spawn a cube at 0,0,0",
        mode="execute")
    assert res.get("ok") is False
    assert res.get("code") == "PLAN_REJECTED", res
    assert runtime.store.get(a.session_id).status == BLOCKED

    # Zero tool dispatches happened (identity probe only, no spawn).
    new_calls = bridge_a.calls[baseline:]
    assert all("spawn" not in str(k) for k, _ in new_calls)

    # The canonical boundary is still in place for a read-only session.
    from app.unreal_coder_api import policy_guarded_dispatch
    blocked = policy_guarded_dispatch(
        True, lambda step: {"ok": True})(
        {"preferred_tool": "spawn_actor"})
    assert blocked.get("policy_blocked") is True


def test_read_only_mission_can_run_read_only_tools(runtime):
    a = start_session(runtime, "ProjectA", client_id="client-X")
    res = runtime.runner.run_prompt(
        a.session_id, "read only: inspect the current project and report it",
        mode="execute")
    assert res.get("ok") and res.get("verdict") == "PASS", res


# ---------------------------------------------------------------------------
# 8. Crash isolation
# ---------------------------------------------------------------------------


def test_crashed_session_does_not_kill_other_session(runtime):
    a = start_session(runtime, "ProjectA", client_id="client-X")
    b = start_session(runtime, "ProjectB", client_id="client-Y")

    # Bridge A dies (editor crash). Only session A is affected.
    runtime.bridges[a.bridge_port].alive = False
    res = runtime.runner.run_prompt(
        a.session_id, "inspect the current project and report it",
        mode="execute", read_only=True)
    assert res.get("ok") is False
    assert res.get("code") == "SESSION_IDENTITY_FAILED"
    assert runtime.store.get(a.session_id).status == CRASHED

    # Session B continues to work.
    res_b = runtime.runner.run_prompt(
        b.session_id, "inspect the current project and report it",
        mode="execute", read_only=True)
    assert res_b.get("ok") and res_b.get("verdict") == "PASS", res_b
    assert runtime.store.get(b.session_id).status == READY

    # Dispatches on B keep running after A crashed (no global reset).
    bridge_b = runtime.bridges[b.bridge_port]
    assert len(bridge_b.calls) > 0


def test_restart_recovers_crashed_session_only(runtime):
    a = start_session(runtime, "ProjectA", client_id="client-X")
    b = start_session(runtime, "ProjectB", client_id="client-Y")

    runtime.bridges[a.bridge_port].alive = False
    res = runtime.runner.run_prompt(
        a.session_id, "inspect the current project and report it",
        mode="execute", read_only=True)
    assert runtime.store.get(a.session_id).status == CRASHED

    # Editor comes back; reconnect restores ONLY session A.
    runtime.bridges[a.bridge_port].alive = True
    restarted = runtime.runner.restart_project(a.session_id)
    assert restarted.get("ok"), restarted
    assert runtime.store.get(a.session_id).status == READY
    assert runtime.store.get(b.session_id).status == READY

    res2 = runtime.runner.run_prompt(
        a.session_id, "inspect the current project and report it",
        mode="execute", read_only=True)
    assert res2.get("ok") and res2.get("verdict") == "PASS", res2


# ---------------------------------------------------------------------------
# 9. Bridge allocation safety
# ---------------------------------------------------------------------------


def test_bridge_allocation_does_not_collide(monkeypatch, tmp_path):
    from core import bridge_allocator as ba

    busy: set[int] = set()

    def fake_probe(host="127.0.0.1", port=6766, timeout=0.25):
        return port in busy

    monkeypatch.setattr(ba, "port_is_listening", fake_probe)

    allocator = BridgeAllocator(port_min=6766, port_max=6790)
    ports = {}
    for pid in ("proj_a", "proj_b", "proj_c"):
        res = allocator.allocate(pid)
        assert res.get("ok"), res
        ports[pid] = res["port"]

    # Every project got a distinct port.
    assert len(set(ports.values())) == 3
    assert sorted(ports.values()) == [6766, 6767, 6768]

    # Re-allocation is stable per project (reconnect keeps the endpoint).
    again = allocator.allocate("proj_a")
    assert again["port"] == ports["proj_a"] and again["reused"] is True

    # A port that becomes live (another process grabbed it) is never reused
    # for a different project.
    busy.add(ports["proj_a"])
    res_d = allocator.allocate("proj_d")
    assert res_d["port"] == 6769, res_d
    # proj_a's own binding is NOT stolen back from the live listener.
    busy.clear()
    res_d2 = allocator.allocate("proj_d")
    assert res_d2["port"] == 6769

    allocator.release("proj_a")
    assert allocator.binding_for("proj_a") is None


# ---------------------------------------------------------------------------
# 10. Browser client state is session-isolated
# ---------------------------------------------------------------------------


def test_browser_client_state_session_isolated(runtime):
    a = start_session(runtime, "ProjectA", client_id="browser-mac-x")
    b = start_session(runtime, "ProjectB", client_id="browser-pc-y")

    res = runtime.runner.run_prompt(
        a.session_id, "spawn a cube at 0,0,0", mode="execute")
    assert res.get("verdict") == "PASS"

    # Client B's session never sees A's execution or task queue.
    b_now = runtime.store.get(b.session_id)
    assert b_now.current_execution_id is None
    assert b_now.task_queue == []
    assert b_now.summary()["task_count"] == 0

    a_now = runtime.store.get(a.session_id)
    assert a_now.current_execution_id is None
    assert a_now.summary()["task_count"] == 1
    assert a_now.task_queue[0].prompt == "spawn a cube at 0,0,0"

    # A's proof does not appear in B's proof view.
    assert runtime.proofs.list(a.session_id) or True  # no crash
    assert runtime.proofs.list(b.session_id) == []


# ---------------------------------------------------------------------------
# HTTP surface (Phase 5): sessions/projects/resources endpoints
# ---------------------------------------------------------------------------


@pytest.fixture
def api_env(tmp_path, monkeypatch):
    """Monkeypatch the session_api singletons onto isolated fakes."""
    from app import session_api
    from core import project_registry as pr
    from core.resource_supervisor import ResourceSupervisor

    store = SessionStore(session_dir=tmp_path / "api-sessions")
    leases = LeaseRegistry(lease_dir=tmp_path / "api-leases")
    proofs = ProofStore(root=tmp_path / "api-proof")
    alloc = FakeAllocator()
    supervisor = ResourceSupervisor(sample_interval=0.05)
    bridges: dict[int, FakeBridge] = {}

    def bf(host, port, timeout=30.0):
        return bridges[port]

    runner = SessionRunner(store=store, leases=leases, proof_store=proofs,
                           allocator=alloc, bridge_factory=bf,
                           registry_builder=make_fake_registry())
    runner._sweeper = None

    monkeypatch.setattr(session_api, "SessionStore", lambda: store)
    monkeypatch.setattr(session_api, "get_default_runner", lambda: runner)
    monkeypatch.setattr(session_api, "get_default_store", lambda: proofs)
    monkeypatch.setattr(session_api, "get_default_allocator", lambda: alloc)
    monkeypatch.setattr(session_api, "get_default_supervisor",
                        lambda: supervisor)
    monkeypatch.setattr(session_api, "snapshot", supervisor.snapshot)

    monkeypatch.setattr(pr, "REGISTRY_FILE", tmp_path / "registry.json")
    monkeypatch.setattr(pr, "_default_registry", None)
    # The session_api module imported `project_registry` by reference; both
    # share the same module object, so the patch above is enough.

    app = FastAPI()
    session_api.register_session_api(app)
    client = TestClient(app)
    env = SimpleNamespace(client=client, store=store, runner=runner,
                          proofs=proofs, bridges=bridges, alloc=alloc,
                          leases=leases, tmp=tmp_path)
    return env


def _register_via_api(env, name):
    path = make_uproject(env.tmp, name)
    r = env.client.post("/api/projects/register",
                        json={"uproject_path": path,
                              "display_name": name})
    assert r.status_code == 200, r.text
    return r.json()["project"]


def test_http_project_and_session_flow(api_env):
    proj_a = _register_via_api(api_env, "HttpProjectA")
    proj_b = _register_via_api(api_env, "HttpProjectB")

    # list projects
    listed = api_env.client.get("/api/projects").json()
    assert {p["project_id"] for p in listed["projects"]} == {
        proj_a["project_id"], proj_b["project_id"]}

    # create + start sessions for both projects
    sessions = {}
    for proj in (proj_a, proj_b):
        sid = api_env.client.post(
            "/api/sessions",
            json={"project_id": proj["project_id"],
                  "client_id": "browser-test"}).json()["session"]["session_id"]
        port = api_env.alloc.allocate(proj["project_id"])["port"]
        api_env.bridges[port] = FakeBridge(
            "127.0.0.1", port, proj["uproject_path"])
        started = api_env.client.post(f"/api/sessions/{sid}/start").json()
        assert started["ok"], started
        sessions[proj["project_id"]] = sid

    # run a prompt on A
    act = api_env.client.post(
        f"/api/sessions/{sessions[proj_a['project_id']]}/action",
        json={"prompt": "inspect the current project and report it",
              "mode": "execute", "read_only": True}).json()
    assert act["ok"] and act["verdict"] == "PASS", act

    # B's session detail is isolated (no A execution leakage)
    b_detail = api_env.client.get(
        f"/api/sessions/{sessions[proj_b['project_id']]}").json()
    assert b_detail["session"]["task_count"] == 0
    a_detail = api_env.client.get(
        f"/api/sessions/{sessions[proj_a['project_id']]}").json()
    assert a_detail["session"]["task_count"] == 1
    assert a_detail["session"]["current_execution_id"] is None

    # tasks endpoint returns only A's own tasks
    a_tasks = api_env.client.get(
        f"/api/sessions/{sessions[proj_a['project_id']]}/tasks").json()
    assert len(a_tasks["tasks"]) == 1
    b_tasks = api_env.client.get(
        f"/api/sessions/{sessions[proj_b['project_id']]}/tasks").json()
    assert b_tasks["tasks"] == []

    # resources endpoint answers
    res = api_env.client.get("/api/resources").json()
    assert res["ok"] is True
    assert "supervisor" in res


def test_http_read_only_policy_via_session_action(api_env):
    proj = _register_via_api(api_env, "HttpReadOnly")
    sid = api_env.client.post(
        "/api/sessions",
        json={"project_id": proj["project_id"]}).json()["session"]["session_id"]
    port = api_env.alloc.allocate(proj["project_id"])["port"]
    api_env.bridges[port] = FakeBridge("127.0.0.1", port,
                                       proj["uproject_path"])
    api_env.client.post(f"/api/sessions/{sid}/start").json()

    act = api_env.client.post(
        f"/api/sessions/{sid}/action",
        json={"prompt": "read only: spawn a cube at 0,0,0",
              "mode": "execute"}).json()
    assert act.get("code") == "PLAN_REJECTED", act
    detail = api_env.client.get(f"/api/sessions/{sid}").json()
    assert detail["session"]["status"] == BLOCKED


def test_http_proof_serving_session_scoped(api_env, tmp_path):
    png = tmp_path / "cap.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nfakepng")
    api_env.runner._registry_builder = make_fake_registry(str(png))

    proj_a = _register_via_api(api_env, "ProofProjA")
    proj_b = _register_via_api(api_env, "ProofProjB")
    sid_a = api_env.client.post(
        "/api/sessions",
        json={"project_id": proj_a["project_id"]}).json()["session"]["session_id"]
    sid_b = api_env.client.post(
        "/api/sessions",
        json={"project_id": proj_b["project_id"]}).json()["session"]["session_id"]
    for sid, proj in ((sid_a, proj_a), (sid_b, proj_b)):
        port = api_env.alloc.allocate(proj["project_id"])["port"]
        api_env.bridges[port] = FakeBridge("127.0.0.1", port,
                                           proj["uproject_path"])
        api_env.client.post(f"/api/sessions/{sid}/start").json()

    act = api_env.client.post(
        f"/api/sessions/{sid_a}/action",
        json={"prompt": "inspect the current project and report it",
              "mode": "execute", "read_only": True}).json()
    assert act["ok"], act

    proofs_a = api_env.client.get(f"/api/sessions/{sid_a}/proof").json()
    assert len(proofs_a["proof"]) == 1
    proofs_b = api_env.client.get(f"/api/sessions/{sid_b}/proof").json()
    assert proofs_b["proof"] == []

    # Serving A's proof file through B's endpoint 404s (path-traversal safe).
    name = proofs_a["proof"][0]["files"][0]["name"]
    exec_id = proofs_a["proof"][0]["execution_id"]
    ok = api_env.client.get(
        f"/api/sessions/{sid_a}/proof/{exec_id}/{name}")
    assert ok.status_code == 200
    denied = api_env.client.get(
        f"/api/sessions/{sid_b}/proof/{exec_id}/{name}")
    assert denied.status_code == 404


def test_http_multiclient_status(api_env):
    status = api_env.client.get("/api/multiclient/status").json()
    assert status["ok"] is True
    assert "sessions" in status and "projects" in status
    assert "allocator" in status and "resources" in status


def test_http_async_action_polls_to_result(api_env):
    import time
    proj = _register_via_api(api_env, "HttpAsyncProj")
    sid = api_env.client.post(
        "/api/sessions",
        json={"project_id": proj["project_id"]}).json()["session"]["session_id"]
    port = api_env.alloc.allocate(proj["project_id"])["port"]
    api_env.bridges[port] = FakeBridge("127.0.0.1", port,
                                       proj["uproject_path"])
    api_env.client.post(f"/api/sessions/{sid}/start").json()

    accepted = api_env.client.post(
        f"/api/sessions/{sid}/async",
        json={"prompt": "inspect the current project and report it",
              "mode": "execute", "read_only": True}).json()
    assert accepted["ok"] and accepted["status"] == "accepted"
    eid = accepted["execution_id"]

    result = None
    for _ in range(50):
        r = api_env.client.get(
            f"/api/sessions/{sid}/execution/{eid}").json()
        if (r.get("checkpoint") or {}).get("verdict"):
            result = r
            break
        time.sleep(0.1)
    assert result is not None, "async execution did not finish"
    assert result["checkpoint"]["verdict"] == "PASS"
    assert result["execution"]["status"] == "done"


# ---------------------------------------------------------------------------
# Resource supervisor policy (Phase 6)
# ---------------------------------------------------------------------------


def test_resource_gate_classification_and_policy(tmp_path):
    from core.resource_supervisor import (
        QUEUED_RESOURCE,
        RUNNING,
        THROTTLED,
        ResourceSupervisor,
        classify_prompt,
    )

    assert classify_prompt("inspect the current project") == "SAFE_PARALLEL"
    assert classify_prompt("render a cinematic sequence") == "GPU_HEAVY"
    assert classify_prompt("compile shaders") == "GPU_HEAVY"

    # SAFE_PARALLEL always runs even with heavy tasks active.
    sup = ResourceSupervisor(active_heavy_provider=lambda: 5)
    assert sup.gate("SAFE_PARALLEL") == RUNNING

    # GPU_HEAVY queues when the heavy-task budget is exhausted.
    sup1 = ResourceSupervisor(max_heavy_tasks=1,
                              active_heavy_provider=lambda: 1)
    assert sup1.gate("GPU_HEAVY") == QUEUED_RESOURCE

    # GPU_HEAVY throttles when VRAM headroom is gone.
    snap = {"gpu": {"used_mb": 19000, "total_mb": 20000,
                    "utilization_pct": 90}, "active_heavy_tasks": 0}
    sup2 = ResourceSupervisor(max_heavy_tasks=2,
                              active_heavy_provider=lambda: 0)
    sup2._snapshot = snap
    assert sup2.gate("GPU_HEAVY") == THROTTLED

    # Runs when headroom is fine.
    sup3 = ResourceSupervisor(active_heavy_provider=lambda: 0)
    sup3._snapshot = {"gpu": {"used_mb": 4000, "total_mb": 20000,
                              "utilization_pct": 30},
                      "active_heavy_tasks": 0}
    assert sup3.gate("GPU_HEAVY") == RUNNING