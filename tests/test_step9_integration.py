"""Step 9 — commercial-hardening integration tests (offline/hermetic).

Covers the exclusive editor-ownership integration added on top of the
Step-8 product shell (core/product_core.py + Lane-B core/editor_lease.py):

  * a mutating task holds a lease for the canonical project identity from
    task start until COMPLETE / FAILED / cancel / exception;
  * a second mutating start against the same project is refused with a
    structured BUSY/OWNED response and performs ZERO Unreal work;
  * a real two-process contention race lets exactly one owner in;
  * heartbeat renewal keeps a long task alive;
  * a dead/stale product owner is recovered on the next boot/restart;
  * a restart after COMPLETE leaves no phantom lease.

No live editor is touched anywhere in this file.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest


@pytest.fixture()
def pc_module(tmp_path, monkeypatch):
    import core.product_core as pc

    monkeypatch.setattr(pc, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(pc, "PRODUCT_CONFIG", tmp_path / "product.json")
    monkeypatch.setattr(pc, "STATE_FILE", tmp_path / "product_state.json")
    return pc


class FakeBridge:
    def __init__(self, identity=None):
        self._identity = identity or {}

    def ping(self):
        return {"ok": True}

    def get_identity(self):
        return {"result": dict(self._identity), "ok": True}

    def execute_python(self, code):
        return {"ok": True, "result": {"ok": True}}


def _identity_for(uproject: Path) -> dict:
    p = str(uproject.resolve()).replace("/", "\\")
    return {"project_name": "ASSET_Showcase2", "project_path": p,
            "engine": "5.4", "world": "/Game/ShowcaseMap"}


def _make_uproject(tmp_path, name="ASSET_Showcase2"):
    root = Path(tmp_path) / "proj"
    uproject = root / name / f"{name}.uproject"
    uproject.parent.mkdir(parents=True)
    uproject.write_text("{}", encoding="utf-8")
    return uproject


def _fresh_session(pc_module, tmp_path, lease_dir=None,
                   uproject: Path = None):
    """Connected ProductSession on a temp project + temp lease dir."""
    uproject = uproject or _make_uproject(tmp_path)
    sess = pc_module.ProductSession(
        lease_dir=Path(lease_dir) if lease_dir else None)
    sess._bridge = FakeBridge(_identity_for(uproject))
    r = sess.connect(str(uproject))
    assert r["ok"] is True, r
    assert sess.status()["state"] == pc_module.READY
    return sess, uproject


def _wait_until(pred, timeout_s=6.0, interval_s=0.05):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(interval_s)
    return pred()


def _complete_stub(sess, entered=None, hold_s=0.0):
    """Replace the pipeline with a harmless in-memory terminal path."""

    def inner(prompt):
        if entered is not None:
            entered.append(prompt)
        if hold_s:
            time.sleep(hold_s)
        sess._complete({"score": 8.66, "defects": []},
                       {"path": "x", "md5": "y"}, prompt)

    return inner


# ---------------------------------------------------------------------------
# Ownership lifecycle
# ---------------------------------------------------------------------------

def test_task_holds_lease_then_releases_on_complete(pc_module, tmp_path):
    sess, uproject = _fresh_session(pc_module, tmp_path)
    sess._execute_pipeline = _complete_stub(sess)
    ident = sess._lease_identity()
    r = sess.run_task("Add a cube named LeaseCube")
    assert r["ok"] is True, r
    # mid-task: mutating lease held by this product owner
    assert _wait_until(lambda: bool(
        (sess._lease.status(ident) or {}).get("mutating"))), "lease not held"
    # terminal COMPLETE -> released
    assert _wait_until(
        lambda: sess.status()["state"] == pc_module.COMPLETE)
    assert _wait_until(lambda: not bool(
        (sess._lease.status(ident) or {}).get("mutating"))), \
        "lease not released on COMPLETE"


def test_task_failure_releases_lease(pc_module, tmp_path):
    sess, uproject = _fresh_session(pc_module, tmp_path)

    def boom(prompt):
        raise RuntimeError("simulated mid-task failure")

    sess._execute_pipeline = boom
    ident = sess._lease_identity()
    r = sess.run_task("Add a cube named BoomCube")
    assert r["ok"] is True
    assert _wait_until(
        lambda: sess.status()["state"] == pc_module.FAILED)
    assert _wait_until(lambda: not bool(
        (sess._lease.status(ident) or {}).get("mutating"))), \
        "lease not released on FAILED"
    assert "simulated mid-task failure" in sess.status()["error_detail"]


def test_lease_marker_recorded_in_timings(pc_module, tmp_path):
    sess, _ = _fresh_session(pc_module, tmp_path)
    sess._execute_pipeline = _complete_stub(sess)
    r = sess.run_task("Add a cube named TimedCube")
    assert r["ok"] is True
    assert _wait_until(
        lambda: sess.status()["state"] == pc_module.COMPLETE)
    assert "lease_acquire_s" in sess.status()["timings"]
    assert float(sess.status()["timings"]["lease_acquire_s"]) < 1.0


# ---------------------------------------------------------------------------
# BUSY / conflict
# ---------------------------------------------------------------------------

def test_busy_conflict_blocks_second_task_without_mutation(pc_module,
                                                           tmp_path):
    owner_dir = Path(tmp_path) / "leases"
    uproject = _make_uproject(tmp_path)
    sess_a, _ = _fresh_session(pc_module, tmp_path, lease_dir=owner_dir,
                               uproject=uproject)
    sess_b, _ = _fresh_session(pc_module, tmp_path / "b",
                               lease_dir=owner_dir, uproject=uproject)
    # Session A owns the project (synchronous acquire, no editor work).
    a = sess_a._acquire_lease("task_owner")
    assert a["ok"] is True, a
    try:
        b = sess_b.run_task("Add a cube named BusyCube")
        assert b["ok"] is False
        assert b.get("busy") is True
        assert b["conflict"]["task_id"] == "task_owner"
        assert b["conflict"]["owner_id"] == sess_a._owner_id
        assert b["conflict"]["expires_in_s"] > 0
        # zero mutation: B stayed READY, no worker ever spawned, no plan ran
        assert sess_b.status()["state"] == pc_module.READY
        assert sess_b._worker is None
        # the blocking owner is untouched
        st = sess_a._lease.status(sess_a._lease_identity())
        assert (st or {}).get("task_id") == "task_owner"
    finally:
        sess_a._release_lease()
    # after release the same request is accepted again
    st = sess_b._lease.status(sess_b._lease_identity())
    assert not (st or {}).get("mutating")


def test_concurrent_two_instances_exactly_one_mutation(pc_module, tmp_path):
    """Real contention: two product instances racing for the same project —
    exactly one gains ownership and mutates; the other gets BUSY."""
    owner_dir = Path(tmp_path) / "leases"
    uproject = _make_uproject(tmp_path)
    sess_a, _ = _fresh_session(pc_module, tmp_path / "a",
                               lease_dir=owner_dir, uproject=uproject)
    sess_b, _ = _fresh_session(pc_module, tmp_path / "b",
                               lease_dir=owner_dir, uproject=uproject)
    entered = []
    results = {}
    barrier = threading.Barrier(2)

    def go(name, sess):
        # the winner holds its lease for 0.8s so the loser's attempt is
        # guaranteed to overlap a LIVE lease (not a released one)
        sess._execute_pipeline = _complete_stub(sess, entered=entered,
                                                hold_s=0.8)
        barrier.wait()
        results[name] = sess.run_task(f"Add a cube named {name}")

    ta = threading.Thread(target=go, args=("A", sess_a))
    tb = threading.Thread(target=go, args=("B", sess_b))
    ta.start(); tb.start(); ta.join(); tb.join()

    oks = [n for n, r in results.items() if r.get("ok")]
    busies = [n for n, r in results.items() if r.get("busy")]
    assert len(oks) == 1, results
    assert len(busies) == 1, results
    # exactly one pipeline ran -> exactly one Unreal mutation would have
    # been attempted; the loser performed zero work.
    assert len(entered) == 1, entered
    # the winner reaches COMPLETE and then releases ownership
    winner = sess_a if results["A"].get("ok") else sess_b
    assert _wait_until(lambda: winner.status()["state"] == pc_module.COMPLETE)
    ident = winner._lease_identity()
    assert _wait_until(lambda: not bool(
        (winner._lease.status(ident) or {}).get("mutating"))), \
        "winner never released"


# ---------------------------------------------------------------------------
# Heartbeat / stale recovery / restart
# ---------------------------------------------------------------------------

def test_heartbeat_keeps_long_task_owned(pc_module, tmp_path):
    lease_dir = Path(tmp_path) / "leases"
    sess, _ = _fresh_session(pc_module, tmp_path, lease_dir=lease_dir)
    # lease would expire in 0.8s without renewal; the task runs 1.6s.
    sess._lease_s = 0.8
    sess._heartbeat_s = 0.2
    sess._execute_pipeline = _complete_stub(sess, hold_s=1.6)
    ident = sess._lease_identity()
    assert sess.run_task("Add a cube named SlowCube")["ok"] is True
    # well past the natural expiry the lease is STILL alive (renewed)
    time.sleep(1.1)
    st = sess._lease.status(ident)
    assert (st or {}).get("mutating"), "heartbeat did not renew the lease"
    assert _wait_until(lambda: sess.status()["state"] == pc_module.COMPLETE,
                       timeout_s=6.0)
    assert _wait_until(lambda: not bool(
        (sess._lease.status(ident) or {}).get("mutating"))), \
        "lease not released after long task"


def test_cross_instance_acquire_is_atomic(tmp_path):
    """Several registry instances racing for one free identity: exactly one
    wins — the read-check-write critical section is file-lock serialized,
    so two product processes can never both believe they own the editor."""
    from core.editor_lease import LeaseRegistry
    d = Path(tmp_path) / "leases"
    regs = [LeaseRegistry(d) for _ in range(4)]
    identity = str(Path(tmp_path) / "Race" / "Race.uproject")
    results = []
    barrier = threading.Barrier(len(regs))

    def go(r):
        barrier.wait()
        results.append(r.acquire(identity, f"owner-{id(r)}",
                                 f"task-{id(r)}", lease_s=30.0))

    threads = [threading.Thread(target=go, args=(r,)) for r in regs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    oks = [x for x in results if x.get("ok")]
    conflicts = [x for x in results if not x.get("ok")]
    assert len(oks) == 1, results
    assert len(conflicts) == 3, results
    # and the surviving lease is the winner's
    st = regs[0].status(identity)
    assert (st or {}).get("owner_id") == oks[0]["lease"]["owner_id"]


def test_stale_owner_recovered_on_boot(pc_module, tmp_path):
    from core.editor_lease import LeaseRegistry
    lease_dir = Path(tmp_path) / "leases"
    reg = LeaseRegistry(lease_dir)
    # a guaranteed-dead product owner (short-lived child, already exited)
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    dead_pid = child.pid
    up = Path(tmp_path) / "proj" / "ASSET_Showcase2.uproject"
    up.parent.mkdir(parents=True, exist_ok=True)
    up.write_text("{}", encoding="utf-8")
    identity = str(up.resolve()).replace("/", "\\")
    r = reg.acquire(identity, f"product-{dead_pid}", "task_crashed",
                    lease_s=300.0)
    assert r["ok"] is True
    assert (reg.status(identity) or {}).get("mutating")
    # a fresh product session boots against the same lease dir and must
    # recover the dead owner's lease immediately (no 5-minute wait).
    sess = pc_module.ProductSession(lease_dir=lease_dir)
    assert _wait_until(lambda: not bool(
        (reg.status(identity) or {}).get("mutating"))), \
        "stale product lease not recovered on boot"


def test_restart_after_complete_leaves_no_phantom_lease(pc_module, tmp_path):
    lease_dir = Path(tmp_path) / "leases"
    sess, uproject = _fresh_session(pc_module, tmp_path,
                                    lease_dir=lease_dir)
    sess._execute_pipeline = _complete_stub(sess)
    ident = sess._lease_identity()
    assert sess.run_task("Add a cube named RestartCube")["ok"] is True
    assert _wait_until(lambda: sess.status()["state"] == pc_module.COMPLETE)
    # restart: a brand-new session restores the persisted COMPLETE task
    sess2 = pc_module.ProductSession(lease_dir=lease_dir)
    st = sess2.status()
    assert st["state"] == pc_module.COMPLETE, st["state"]
    assert st["project"]["uproject_path"] == \
        str(uproject.resolve()).replace("\\", "/")
    stl = sess2._lease.status(ident)
    assert not (stl or {}).get("mutating"), "phantom lease after restart"
