"""Cinematic tools registered in the canonical tool registry (hermetic).

Confirms build_registry wires the V2 cinematic surface when a bridge is
present (the same path the mission executor uses). No live connection is
made — UnrealBridge is only constructed, never used.
"""

from __future__ import annotations

from core.tool_registry import build_registry
from tools.unreal.unreal_bridge import UnrealBridge


def _dummy(*args, **kwargs):
    return {}


def _build():
    return build_registry(
        _dummy, _dummy, _dummy, _dummy,
        _dummy, _dummy, _dummy, _dummy,
        bridge=UnrealBridge(),
    )


def test_registry_exposes_cinematic_tools():
    registry = _build()
    for name in ("probe_movie_render_queue", "read_cine_camera",
                 "run_cinematic_mission"):
        assert name in registry, name
        spec = registry[name]
        assert callable(spec.func)
        assert isinstance(spec.args, dict)


def test_registry_without_bridge_skips_live_cinematic_tools():
    registry = build_registry(
        _dummy, _dummy, _dummy, _dummy,
        _dummy, _dummy, _dummy, _dummy,
        bridge=None,
    )
    for name in ("probe_movie_render_queue", "read_cine_camera",
                 "run_cinematic_mission"):
        assert name not in registry


def test_existing_tools_still_registered_alongside_cinematic():
    registry = _build()
    for name in ("unreal_ping", "create_level_sequence", "save_sequence",
                 "capture_unreal_viewport", "blender_status"):
        assert name in registry, name
