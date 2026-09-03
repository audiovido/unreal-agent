"""Hermetic tests for core/editor_lease.py (no editor, controllable clock)."""
from __future__ import annotations

import threading

from core import editor_lease as el


class FakeClock:
    def __init__(self, t=1000.0):
        self._t = float(t)

    def time(self) -> float:
        return self._t

    def advance(self, s: float) -> None:
        self._t += s


def _registry(tmp_path, clock) -> el.LeaseRegistry:
    return el.LeaseRegistry(lease_dir=tmp_path / "leases", clock=clock)


IDENT = {"project_path": r"C:\Proj\ASSET_Showcase2.uproject",
         "project_name": "ASSET_Showcase2"}


def test_canonical_identity_normalises(tmp_path):
    a = el.canonical_identity({"project_path": r"C:\A\B.uproject"})
    b = el.canonical_identity("c:/a/b.uproject")
    c = el.canonical_identity({"project_path": "C:/a/B.uproject",
                               "port": 9999})  # port is irrelevant
    assert a == b == c
    assert "9999" not in c
    assert el.canonical_identity({"project_name": "OnlyName"}) == \
        "onlyname"


def test_acquire_then_conflict(tmp_path):
    clock = FakeClock()
    reg = _registry(tmp_path, clock)
    first = reg.acquire(IDENT, "owner-a", "task-1", lease_s=60)
    assert first["ok"] is True and first["lease"]["mutating"] is True
    second = reg.acquire(IDENT, "owner-b", "task-2", lease_s=60)
    assert second["ok"] is False
    assert second["conflict"]["owner_id"] == "owner-a"
    assert second["conflict"]["task_id"] == "task-1"


def test_read_only_never_conflicts(tmp_path):
    clock = FakeClock()
    reg = _registry(tmp_path, clock)
    assert reg.acquire(IDENT, "m1", "t1", read_only=False)["ok"] is True
    # read-only inspectors may run alongside a mutator
    ro = reg.acquire(IDENT, "r1", "t-ro", read_only=True)
    assert ro["ok"] is True
    # a second mutator still blocked while m1's lease is live
    assert reg.acquire(IDENT, "m2", "t2")["ok"] is False
    # but two read-only watchers coexist
    assert reg.acquire(IDENT, "r2", "t-ro2", read_only=True)["ok"] is True


def test_expiry_and_stale_recovery(tmp_path):
    clock = FakeClock()
    reg = _registry(tmp_path, clock)
    reg.acquire(IDENT, "crashed-owner", "task-x", lease_s=30)
    clock.advance(31)
    st = reg.status(IDENT)
    assert st["expired"] is True and st["owned"] is False
    fresh = reg.acquire(IDENT, "new-owner", "task-y", lease_s=60)
    assert fresh["ok"] is True
    assert fresh["lease"]["recovered_stale"] is True
    assert fresh["lease"]["owner_id"] == "new-owner"


def test_renew_extends_expiry(tmp_path):
    clock = FakeClock()
    reg = _registry(tmp_path, clock)
    reg.acquire(IDENT, "o1", "t1", lease_s=30)
    clock.advance(20)
    renewed = reg.renew(IDENT, "o1", lease_s=30)
    assert renewed["ok"] is True
    clock.advance(25)  # would have expired at 30s; renewed -> alive
    assert reg.status(IDENT)["expired"] is False
    # wrong owner cannot renew
    assert reg.renew(IDENT, "intruder")["ok"] is False


def test_release_semantics(tmp_path):
    clock = FakeClock()
    reg = _registry(tmp_path, clock)
    reg.acquire(IDENT, "o1", "t1")
    wrong = reg.release(IDENT, "o2")
    assert wrong["ok"] is False
    ok = reg.release(IDENT, "o1")
    assert ok["ok"] is True
    assert reg.status(IDENT)["owned"] is False
    # releasing again is a no-op success
    assert reg.release(IDENT, "o1")["ok"] is True


def test_force_release_clears_crash_lock(tmp_path):
    clock = FakeClock()
    reg = _registry(tmp_path, clock)
    reg.acquire(IDENT, "ghost", "t-ghost", lease_s=100000)
    res = reg.force_release(IDENT, reason="operator override")
    assert res["ok"] is True
    assert res["released"]["mutating"]["owner_id"] == "ghost"
    assert reg.acquire(IDENT, "o2", "t2")["ok"] is True


def test_different_identities_are_independent(tmp_path):
    clock = FakeClock()
    reg = _registry(tmp_path, clock)
    other = {"project_path": "C:/Other/Other.uproject"}
    reg.acquire(IDENT, "a", "t1")
    assert reg.acquire(other, "b", "t2")["ok"] is True
    assert reg.acquire({"project_path": "C:/Other/Other.uproject",
                        "port": 6766}, "c", "t3")["ok"] is False  # same other


def test_persistence_across_registry_instances(tmp_path):
    clock = FakeClock()
    reg1 = _registry(tmp_path, clock)
    reg1.acquire(IDENT, "o1", "t1", lease_s=60)
    reg2 = _registry(tmp_path, clock)
    st = reg2.status(IDENT)
    assert st["owned"] is True and st["owner_id"] == "o1"
    # expired lease is recoverable from a fresh registry too
    clock.advance(90)
    reg3 = _registry(tmp_path, clock)
    assert reg3.acquire(IDENT, "o2", "t2")["ok"] is True


def test_concurrent_mutating_acquire_single_winner(tmp_path):
    clock = FakeClock()
    reg = _registry(tmp_path, clock)
    results = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        r = reg.acquire(IDENT, f"owner-{i}", f"task-{i}")
        with lock:
            results.append(r)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    winners = [r for r in results if r.get("ok")]
    assert len(winners) == 1
    assert sum(1 for r in results if not r.get("ok")) == 7


def test_list_leases_shape(tmp_path):
    clock = FakeClock()
    reg = _registry(tmp_path, clock)
    reg.acquire(IDENT, "o1", "t1")
    reg.acquire({"project_path": "C:/Other/Other.uproject"}, "o2", "t2")
    leases = reg.list_leases()
    assert len(leases) == 2
    assert {le["owner_id"] for le in leases} == {"o1", "o2"}
