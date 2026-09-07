"""AIVIDO parallel QA — hermetic idle-driver regression suite.

Tests the procedural human idle driver
(assetlib/tests/ue/ASSET_Showcase2/Content/Python/aivido_idle_driver.py)
WITHOUT any live Unreal Editor access. The real driver module is imported
under a fully fake `unreal` module injected into sys.modules, so every code
path (tick callback, actor discovery, start/stop/restore, error handling)
is exercised offline against a deterministic fake editor world.

Covered contracts:
  * duplicate-start prevention (start while running must not re-register)
  * stop restores every driven actor to its exact captured base pose
  * bounded motion: tick-driven offsets never exceed the profile amplitudes
    and repeated start/stop cycles never drift the actors from their base
  * invalid actor handling: actors that throw during label read are skipped;
    actors that throw during restore do not block the other restores; tick
    errors are swallowed (logged, never propagated into the editor loop)
  * reload-safe behavior: after stop, a fresh start works and state resets
  * include_editor mode drives game-world + editor-world characters
"""

from __future__ import annotations

import importlib
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DRIVER_DIR = ROOT / "assetlib" / "tests" / "ue" / "ASSET_Showcase2" / "Content" / "Python"


# --------------------------------------------------------------------------
# Fake `unreal` surface (only what the driver touches)
# --------------------------------------------------------------------------
class FakeVector:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = float(x), float(y), float(z)

    def __eq__(self, other):
        return (self.x, self.y, self.z) == (other.x, other.y, other.z)

    def __repr__(self):
        return f"Vector({self.x}, {self.y}, {self.z})"


class FakeRotator:
    def __init__(self, pitch, yaw, roll):
        self.pitch, self.yaw, self.roll = float(pitch), float(yaw), float(roll)

    def __eq__(self, other):
        return (self.pitch, self.yaw, self.roll) == (other.pitch, other.yaw, other.roll)

    def __repr__(self):
        return f"Rotator({self.pitch}, {self.yaw}, {self.roll})"


class FakeActor:
    def __init__(self, label, x=0.0, y=0.0, z=0.0, yaw=180.0,
                 raise_on_label=False, raise_on_set_loc=False, raise_on_set_rot=False):
        self.label = label
        self.loc = FakeVector(x, y, z)
        self.yaw = float(yaw)
        self.raise_on_label = raise_on_label
        self.raise_on_set_loc = raise_on_set_loc
        self.raise_on_set_rot = raise_on_set_rot
        self.writes = 0

    def get_actor_label(self):
        if self.raise_on_label:
            raise RuntimeError("label read failed")
        return self.label

    def get_actor_location(self):
        return self.loc

    def get_actor_rotation(self):
        return FakeRotator(0.0, self.yaw, 0.0)

    def set_actor_location(self, loc, sweep, teleport):
        if self.raise_on_set_loc:
            raise RuntimeError("set_actor_location failed")
        self.loc = loc
        self.writes += 1

    def set_actor_rotation(self, rot, sweep):
        if self.raise_on_set_rot:
            raise RuntimeError("set_actor_rotation failed")
        self.yaw = rot.yaw
        self.writes += 1

    def pose(self):
        return (self.loc.x, self.loc.y, self.loc.z, self.yaw)


class FakeWorld:
    def __init__(self, actors):
        self.actors = list(actors)


class FakeEditorSubsystem:
    def __init__(self, game_actors=None, editor_actors=None):
        self.game_world = FakeWorld(game_actors or [])
        self.editor_world = FakeWorld(editor_actors or [])

    def get_game_world(self):
        return self.game_world

    def get_editor_world(self):
        return self.editor_world


class FakeUnreal:
    def __init__(self, subsystem):
        self._subsystem = subsystem
        self.register_calls = 0
        self.unregister_calls = 0
        self.errors = []
        self.Actor = type("Actor", (), {})
        self.UnrealEditorSubsystem = type("UnrealEditorSubsystem", (), {})

    def Vector(self, x, y, z):
        return FakeVector(x, y, z)

    def Rotator(self, pitch, yaw, roll):
        return FakeRotator(pitch, yaw, roll)

    def get_editor_subsystem(self, cls):
        return self._subsystem

    def register_slate_post_tick_callback(self, fn):
        self.register_calls += 1
        self._tick_fn = fn
        return f"handle-{self.register_calls}"

    def unregister_slate_post_tick_callback(self, handle):
        self.unregister_calls += 1

    def log_error(self, msg):
        self.errors.append(msg)

    def log_traceback(self):
        return "<fake traceback>"

    class GameplayStatics:
        @staticmethod
        def get_all_actors_of_class(world, cls):
            return list(world.actors)


class FakeClock:
    """Deterministic wall clock so tick phases advance without real sleeps."""

    def __init__(self, start=1000.0):
        self.now = start

    def advance(self, seconds):
        self.now += seconds

    def time(self):
        return self.now


@pytest.fixture()
def env(monkeypatch):
    """Fresh driver module + fake unreal per test (module state is global)."""
    sys.modules.pop("aivido_idle_driver", None)
    driver_file = DRIVER_DIR / "aivido_idle_driver.py"
    assert driver_file.exists(), f"driver missing: {driver_file}"
    sys.path.insert(0, str(DRIVER_DIR))

    clock = FakeClock()
    subsystem = FakeEditorSubsystem()
    fake = FakeUnreal(subsystem)
    sys.modules["unreal"] = fake
    monkeypatch.setattr(sys, "path", sys.path)  # keep path stable for importlib

    mod = importlib.import_module("aivido_idle_driver")
    monkeypatch.setattr(mod.time, "time", clock.time)  # deterministic clock
    mod._HANDLE = None
    mod._STATE.update({"running": False, "chars": [], "t0": None, "calls": 0, "include_editor": False})

    yield mod, fake, subsystem, clock

    sys.modules.pop("aivido_idle_driver", None)
    sys.modules.pop("unreal", None)


def _humans(n, prefix="AVIDO_Human", **kw):
    return [FakeActor(f"{prefix}_{i:02d}", x=float(i * 100), y=700.0, z=0.0, **kw) for i in range(n)]


def _run_ticks(mod, clock, seconds, step=0.25):
    steps = int(seconds / step)
    for _ in range(steps):
        clock.advance(step)
        mod._tick(step)


# --------------------------------------------------------------------------
# Duplicate-start prevention
# --------------------------------------------------------------------------
class TestDuplicateStart:
    def test_second_start_is_idempotent(self, env):
        mod, fake, _, _ = env
        first = mod.start_idle_driver()
        assert first["ok"] is True
        assert first.get("already") is not True
        second = mod.start_idle_driver()
        assert second["ok"] is True
        assert second.get("already") is True
        assert fake.register_calls == 1, "second start must not re-register the tick callback"

    def test_stats_reflect_single_running_instance(self, env):
        mod, fake, _, _ = env
        mod.start_idle_driver()
        mod.start_idle_driver()
        st = mod.idle_stats()
        assert st["running"] is True
        assert fake.register_calls == 1


# --------------------------------------------------------------------------
# Stop restores exact base transforms
# --------------------------------------------------------------------------
class TestStopRestores:
    def test_stop_restores_all_actors_exactly(self, env):
        mod, fake, subsystem, clock = env
        actors = _humans(3)
        subsystem.game_world.actors = actors
        bases = [a.pose() for a in actors]
        mod.start_idle_driver()
        _run_ticks(mod, clock, 5.0)
        assert any(a.pose() != b for a, b in zip(actors, bases)), "motion must move actors"
        result = mod.stop_idle_driver()
        assert result["ok"] is True
        assert result["restored"] == 3
        assert result["calls"] > 0
        for a, b in zip(actors, bases):
            assert a.pose() == b, f"{a.label} not restored to base"

    def test_stop_is_idempotent(self, env):
        mod, fake, subsystem, clock = env
        subsystem.game_world.actors = _humans(2)
        mod.start_idle_driver()
        _run_ticks(mod, clock, 2.0)
        r1 = mod.stop_idle_driver()
        r2 = mod.stop_idle_driver()
        assert r1["restored"] == 2
        assert r2["restored"] == 0, "second stop must have nothing left to restore"
        assert mod.idle_stats()["running"] is False

    def test_no_cumulative_drift_across_cycles(self, env):
        mod, fake, subsystem, clock = env
        actors = _humans(4)
        subsystem.game_world.actors = actors
        bases = [a.pose() for a in actors]
        for _ in range(5):
            mod.start_idle_driver()
            _run_ticks(mod, clock, 3.0)
            mod.stop_idle_driver()
        for a, b in zip(actors, bases):
            assert a.pose() == b, f"drift after repeated start/stop: {a.label}"


# --------------------------------------------------------------------------
# Bounded motion / no cumulative drift while running
# --------------------------------------------------------------------------
class TestBoundedMotion:
    def test_offsets_bounded_by_profile_amplitudes(self, env):
        mod, fake, subsystem, clock = env
        actors = _humans(8)
        subsystem.game_world.actors = actors
        bases = [a.pose() for a in actors]
        mod.start_idle_driver()
        _run_ticks(mod, clock, 30.0)  # > 4 full breath cycles for every profile
        max_dz = max_dx = max_dy = 0.0
        for a, b in zip(actors, bases):
            max_dz = max(max_dz, abs(a.loc.z - b[2]))
            max_dx = max(max_dx, abs(a.loc.x - b[0]))
            max_dy = max(max_dy, abs(a.loc.y - b[1]))
        # amplitude ceiling: breath <= 3.6 cm, sway <= 2.2 cm + small numeric slack
        assert max_dz <= 4.2, f"breathing bob exceeded amplitude: {max_dz}"
        assert max_dx <= 2.6, f"sway x exceeded amplitude: {max_dx}"
        assert max_dy <= 1.4, f"sway y exceeded amplitude: {max_dy}"
        assert max_dz >= 1.0, "motion must be non-trivial (real breathing) for at least one actor"

    def test_yaw_offset_bounded(self, env):
        mod, fake, subsystem, clock = env
        actors = _humans(2)
        subsystem.game_world.actors = actors
        bases = [a.pose() for a in actors]
        mod.start_idle_driver()
        _run_ticks(mod, clock, 60.0)
        for a, b in zip(actors, bases):
            assert abs(a.yaw - b[3]) <= 2.6, f"gaze yaw exceeded amplitude: {a.label}"

    def test_driver_call_rate_advances(self, env):
        mod, fake, subsystem, clock = env
        subsystem.game_world.actors = _humans(2)
        mod.start_idle_driver()
        _run_ticks(mod, clock, 2.0)
        assert mod.idle_stats()["calls"] > 0


# --------------------------------------------------------------------------
# Invalid actor handling
# --------------------------------------------------------------------------
class TestInvalidActors:
    def test_actor_with_broken_label_is_skipped(self, env):
        mod, fake, subsystem, clock = env
        good = _humans(2)
        broken = FakeActor("AVIDO_Human_BROKEN", raise_on_label=True)
        subsystem.game_world.actors = good + [broken]
        mod.start_idle_driver()
        _run_ticks(mod, clock, 1.0)
        assert len(mod._STATE["chars"]) == 2, "broken-label actor must be skipped, not crash the driver"
        assert not fake.errors, "label failure must be swallowed silently, not logged as driver error"

    def test_restore_failure_does_not_block_other_restores(self, env):
        mod, fake, subsystem, clock = env
        good1 = FakeActor("AVIDO_Human_01", x=100.0, y=700.0, z=0.0)
        bad = FakeActor("AVIDO_Human_BAD", x=200.0, y=700.0, z=0.0, raise_on_set_loc=True)
        good2 = FakeActor("AVIDO_Human_02", x=300.0, y=700.0, z=0.0)
        subsystem.game_world.actors = [good1, bad, good2]
        bases = {a.label: a.pose() for a in (good1, good2)}
        mod.start_idle_driver()
        _run_ticks(mod, clock, 2.0)
        result = mod.stop_idle_driver()
        assert result["restored"] == 2, "only the healthy actors can restore"
        assert good1.pose() == bases["AVIDO_Human_01"]
        assert good2.pose() == bases["AVIDO_Human_02"]

    def test_tick_error_is_swallowed_and_logged(self, env):
        mod, fake, subsystem, clock = env
        subsystem.game_world.actors = [FakeActor("AVIDO_Human_01", raise_on_set_loc=True)]
        mod.start_idle_driver()
        clock.advance(1.0)
        mod._tick(1.0)  # set_actor_location raises inside _apply
        assert fake.errors, "tick failure must be surfaced via unreal.log_error"
        # driver must stay alive and report running state
        assert mod.idle_stats()["running"] is True

    def test_no_world_is_a_safe_noop(self, env):
        mod, fake, subsystem, clock = env
        subsystem.game_world.actors = []
        subsystem.editor_world.actors = []
        mod.start_idle_driver()
        clock.advance(1.0)
        mod._tick(1.0)
        assert mod._STATE["chars"] == []
        assert not fake.errors


# --------------------------------------------------------------------------
# Reload-safe behavior
# --------------------------------------------------------------------------
class TestReloadSafe:
    def test_start_after_stop_works(self, env):
        mod, fake, subsystem, clock = env
        subsystem.game_world.actors = _humans(1)
        mod.start_idle_driver()
        mod.stop_idle_driver()
        again = mod.start_idle_driver()
        assert again.get("already") is not True, "fresh start after stop must not report already-running"
        assert mod.idle_stats()["running"] is True
        _run_ticks(mod, clock, 1.0)
        assert mod.idle_stats()["calls"] > 0
        mod.stop_idle_driver()

    def test_stats_reset_on_restart(self, env):
        mod, fake, subsystem, clock = env
        subsystem.game_world.actors = _humans(1)
        mod.start_idle_driver()
        _run_ticks(mod, clock, 1.0)
        mod.stop_idle_driver()
        mod.start_idle_driver()
        st = mod.idle_stats()
        assert st["chars"] == 0  # repopulated on first tick
        assert st["calls"] == 0


# --------------------------------------------------------------------------
# include_editor mode (visual-proof path: drives editor world too)
# --------------------------------------------------------------------------
class TestIncludeEditor:
    def test_include_editor_drives_both_worlds(self, env):
        mod, fake, subsystem, clock = env
        game = _humans(2, prefix="AVIDO_Human")
        editor = _humans(2, prefix="AVIDO_Agent")
        subsystem.game_world.actors = game
        subsystem.editor_world.actors = editor
        mod.start_idle_driver(include_editor=True)
        _run_ticks(mod, clock, 1.0)
        assert len(mod._STATE["chars"]) == 4, "include_editor must drive game + editor characters"
        mod.stop_idle_driver()

    def test_default_mode_drives_game_world_only(self, env):
        mod, fake, subsystem, clock = env
        subsystem.game_world.actors = _humans(2, prefix="AVIDO_Human")
        subsystem.editor_world.actors = _humans(2, prefix="AVIDO_Agent")
        mod.start_idle_driver()
        _run_ticks(mod, clock, 1.0)
        assert len(mod._STATE["chars"]) == 2, "default mode must not drive editor-world characters"
        mod.stop_idle_driver()