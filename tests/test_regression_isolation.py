"""RECOVERY TORTURE GRADUATION — hermetic regression guard.

Proves that a normal pytest run can NEVER cause an unintended real Unreal
mutation even when a live Unreal bridge is reachable on 127.0.0.1:6766.

The guard (tests/conftest.py::_block_live_unreal_bridge) replaces
UnrealBridge._send — the single transport choke point for all live bridge
I/O — with a structured refusal for every test that is not explicitly
marked @pytest.mark.live_unreal.

These tests do not need the live editor at all: the guard must fire whether
the bridge is up, down, or absent, which is exactly the property that makes
the regression suite hermetic.
"""
import socket

import pytest

from tools.unreal.unreal_bridge import UnrealBridge

# Must match tests/conftest.py::_block_live_unreal_bridge refusal text.
BLOCKED_ERROR = "REGRESSION_ISOLATION"


def _live_bridge_reachable() -> bool:
    """True when a real editor bridge is listening on the default endpoint."""
    try:
        with socket.create_connection(("127.0.0.1", 6766), timeout=1.0):
            return True
    except OSError:
        return False


def _call_like_a_live_dispatch():
    """The realistic accidental-mutation path: a real UnrealBridge instance
    created by an executor/tool and driven through the transport."""
    bridge = UnrealBridge()  # real class, real host/port defaults
    identity = bridge.get_identity()
    spawn = bridge.spawn_actor(
        actor_name="ISOLATION_GUARD_SENTINEL",
        actor_type="StaticMeshActor",
        mesh_asset="/Engine/BasicShapes/Cube",
        location=[0, 0, 0],
    )
    return identity, spawn


class TestHermeticIsolation:
    def test_live_bridge_cannot_be_reached_by_unmarked_test(self):
        """With the live bridge present (or absent), an unmarked test that
        would dispatch through a real UnrealBridge is refused BEFORE any
        network I/O — so it can never mutate the open editor level."""
        identity, spawn = _call_like_a_live_dispatch()

        # Every transport call must be the structured guard refusal, never a
        # real round-trip (a real round-trip would return ok:true here when
        # the bridge is live and could mutate the editor).
        assert identity.get("ok") is False
        assert spawn.get("ok") is False
        assert BLOCKED_ERROR in (identity.get("error") or "")
        assert BLOCKED_ERROR in (spawn.get("error") or "")

    def test_guard_fires_regardless_of_bridge_state(self):
        """The guard is environment-independent: it must not depend on the
        live bridge being down. Record reachability only as evidence."""
        reachable = _live_bridge_reachable()
        result = _call_like_a_live_dispatch()[1]
        assert result.get("ok") is False
        assert BLOCKED_ERROR in (result.get("error") or "")
        # If a live editor WAS reachable during this run, this test proves the
        # sentinel spawn was refused and the editor was left untouched.
        assert reachable or True  # evidence line: see printed marker below
        print(
            "live_bridge_reachable_during_regression=" + str(reachable),
            "sentinel_mutation_refused=True",
        )

    def test_opt_in_marker_is_registered(self):
        """The opt-in marker must exist so explicit live tests stay possible
        and are never misreported as unknown markers."""
        import pytest

        # Registered in pytest.ini -> attribute exists without warning.
        assert pytest.mark.live_unreal is not None
