"""Overnight release-candidate hardening regressions (offline, no live API).

Covers the three fixes shipped on aivido/overnight-release-95:
1. SessionStore self-heal: sessions persisted by per-request store instances
   are visible to long-lived runner stores (no more cross-store 500s).
2. Explicit unsatisfiable tool requests fail missions truthfully up front
   (no planner substitution -> fake PASS).
3. Step dispatch on an unknown tool is truthful (ok=False, error names tool).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.session_execution import (
    _extract_requested_tools,
    _production_dispatch,
)
from core.session_model import SessionStore


def _tmp_store(tmp_path: Path) -> SessionStore:
    return SessionStore(session_dir=tmp_path)


# -- 1. cross-store visibility ------------------------------------------------
def test_store_self_heals_sessions_from_disk(tmp_path):
    a = _tmp_store(tmp_path)
    b = _tmp_store(tmp_path)
    s = a.create(project_id="proj_test", project_path="C:/tmp/proj",
                 project_name="Proj")
    # store b never saw this session in memory; must load it from disk
    assert b.get(s.session_id) is not None
    assert b.get(s.session_id).project_id == "proj_test"


def test_store_missing_session_stays_none(tmp_path):
    b = _tmp_store(tmp_path)
    assert b.get("sess_missing") is None


# -- 2. explicit tool request extraction --------------------------------------
def test_extract_requested_tools_named():
    got = _extract_requested_tools(
        "read only: call the tool named definitely_not_a_real_tool_xyz "
        "and report its exact result")
    assert got == {"definitely_not_a_real_tool_xyz"}


def test_extract_requested_tools_real_and_generic():
    assert _extract_requested_tools(
        "use tool named capture_unreal_viewport on the level"
        ) == {"capture_unreal_viewport"}
    # generic "tool" mentions without an identifier extract nothing
    assert _extract_requested_tools("pick the right tool for the job") == set()


# -- 3. unknown-tool dispatch is truthful -------------------------------------
def test_dispatch_unknown_tool_truthful():
    dispatch = _production_dispatch({})
    out = dispatch({"preferred_tool": "no_such_tool", "parameters": {}})
    assert out.get("ok") is False
    assert "Unknown tool no_such_tool" in str(out.get("error"))


# -- store round-trip hardening (tmp persistence stays valid json) ------------
def test_store_persisted_file_is_valid_json(tmp_path):
    a = _tmp_store(tmp_path)
    s = a.create(project_id="proj_json", project_path="C:/tmp/pj",
                 project_name="Pj")
    p = tmp_path / f"{s.session_id}.json"
    assert p.is_file()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data.get("session_id") == s.session_id
