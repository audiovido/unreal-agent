"""Hermetic tests for stable actor identity on UE 5.7.

Pins the contract that duplicate Outliner labels and phantom duplicate
handles can never hard-fail a verification step with "Ambiguous actor label",
while internal names remain the unique runtime identity.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.actor_identity import (
    resolve_actor,
    unreal_actor_resolution_prelude,
)


def cand(name, label=None, readable=True):
    return {"name": name, "label": label if label is not None else name,
            "readable": readable, "actor": object()}


class TestResolveActor:
    def test_unique_internal_name_wins(self):
        cands = [cand("AIVIDO_KeyWarm_2", "AIVIDO_KeyWarm"), cand("Floor", "AIVIDO_Floor")]
        r = resolve_actor("AIVIDO_KeyWarm_2", cands)
        assert r["status"] == "resolved" and r["match"] == "name"
        assert r["ambiguous_label"] is False

    def test_unique_label_resolves(self):
        cands = [cand("KeyWarm", "AIVIDO_KeyWarm")]
        r = resolve_actor("AIVIDO_KeyWarm", cands)
        assert r["status"] == "resolved" and r["match"] == "label"

    def test_duplicate_labels_resolve_deterministically_not_ambiguously(self):
        """The production failure shape: two actors share one Outliner label
        while their internal names differ from the query."""
        cands = [cand("UA_Blender_Asset_B", "UA_Blender_Asset"),
                 cand("UA_Blender_Asset_A", "UA_Blender_Asset")]
        r = resolve_actor("UA_Blender_Asset", cands)
        assert r["status"] == "resolved"
        assert r["ambiguous_label"] is True
        assert r["actor"]["name"] == "UA_Blender_Asset_A"  # lowest name wins
        assert r["matches"] == ["UA_Blender_Asset_A", "UA_Blender_Asset_B"]

    def test_phantom_handles_are_dropped(self):
        cands = [cand("PhantomA", "Ghost", readable=False),
                 cand("RealOne", "Ghost")]
        r = resolve_actor("Ghost", cands)
        assert r["status"] == "resolved"
        assert r["actor"]["name"] == "RealOne"
        assert r["ambiguous_label"] is False

    def test_phantom_only_label_is_reported_not_hidden(self):
        cands = [cand("PhantomA", "Ghost", readable=False)]
        r = resolve_actor("Ghost", cands)
        assert r["status"] == "resolved_phantom_only"
        assert r["actor"] is None

    def test_not_found(self):
        assert resolve_actor("Nope", [cand("A", "B")])["status"] == "not_found"

    def test_empty_query_not_found(self):
        assert resolve_actor("", [cand("A")])["status"] == "not_found"

    def test_strict_mode_still_reports_ambiguity(self):
        cands = [cand("B", "Dup"), cand("A", "Dup")]
        r = resolve_actor("Dup", cands, require_unique_label=True)
        assert r["status"] == "ambiguous"
        assert r["matches"] == ["A", "B"]

    def test_duplicate_internal_names_flagged_but_resolved(self):
        cands = [cand("Same"), cand("Same")]
        r = resolve_actor("Same", cands)
        assert r["status"] == "resolved"
        assert r["ambiguous_label"] is True


class _FakeUnrealActor:
    def __init__(self, name, label=None, broken=False):
        self._name = name
        self._label = label or name
        self._broken = broken

    def get_name(self):
        if self._broken:
            raise RuntimeError("phantom handle")
        return self._name

    def get_actor_label(self):
        if self._broken:
            raise RuntimeError("phantom handle")
        return self._label


class _FakeSubsystem:
    def __init__(self, actors):
        self._actors = actors

    def get_all_level_actors(self):
        return self._actors


class _FakeUnreal:
    def __init__(self, actors):
        self.EditorActorSubsystem = type("EAS", (), {})
        self._sub = _FakeSubsystem(actors)

    def get_editor_subsystem(self, _cls):
        return self._sub


class TestUnrealPreludeEndToEnd:
    def _run_prelude(self, actors):
        # Mirror the real bridge embed exactly: resolve_actor source + prelude.
        import inspect
        from core import actor_identity as ai
        ns: dict = {"unreal": _FakeUnreal(actors)}
        src = "from typing import Any, Dict, List\n" + \
            inspect.getsource(ai.resolve_actor) + "\n" + \
            unreal_actor_resolution_prelude()
        exec(compile(src, "<prelude>", "exec"), ns)
        return ns

    def test_prelude_resolves_duplicate_labels(self):
        actors = [_FakeUnrealActor("HandleB", "SharedLabel"),
                  _FakeUnrealActor("HandleA", "SharedLabel")]
        ns = self._run_prelude(actors)
        r = ns["__aivido_resolve_actor__"]("SharedLabel")
        assert r["status"] == "resolved"
        assert r["actor"]["actor"] is actors[1]  # lowest internal name wins
        assert r["ambiguous_label"] is True
        assert r["matches"] == ["HandleA", "HandleB"]

    def test_prelude_drops_phantom_handles(self):
        actors = [_FakeUnrealActor("Phantom", "Dup", broken=True),
                  _FakeUnrealActor("Real", "Dup")]
        ns = self._run_prelude(actors)
        r = ns["__aivido_resolve_actor__"]("Dup")
        assert r["status"] == "resolved"
        assert r["actor"]["name"] == "Real"

    def test_prelude_not_found_shape(self):
        ns = self._run_prelude([_FakeUnrealActor("A")])
        r = ns["__aivido_resolve_actor__"]("Missing")
        assert r["status"] == "not_found"


class TestBridgeEmbed:
    def test_bridge_prelude_renders_compilable_script(self):
        from tools.unreal.unreal_bridge import UnrealBridge
        bridge = UnrealBridge.__new__(UnrealBridge)
        prelude = bridge._identity_script_prelude()
        assert "def resolve_actor(" in prelude
        assert "__aivido_resolve_actor__" in prelude
        # The embedded prelude must be syntactically valid Python.
        compile(prelude, "<embed>", "exec")

    def test_embedded_prelude_executes_against_fake_unreal(self):
        from tools.unreal.unreal_bridge import UnrealBridge
        bridge = UnrealBridge.__new__(UnrealBridge)
        ns: dict = {"unreal": _FakeUnreal([_FakeUnrealActor("X", "Dup"),
                                           _FakeUnrealActor("Y", "Dup")])}
        exec(compile(bridge._identity_script_prelude(), "<embed>", "exec"), ns)
        r = ns["__aivido_resolve_actor__"]("Dup")
        assert r["status"] == "resolved"
        assert r["actor"]["name"] == "X"
