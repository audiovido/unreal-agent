"""P2 contract tests: run the same scenario table as the milestone runner
through headless Blender and assert the observable JSON contract.

Slow by design (one Blender boot per scenario) but bounded; skipped when no
Blender 4.2 LTS is installed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
ASSETLIB = TOOLS.parent
if str(ASSETLIB.parent) not in sys.path:
    sys.path.insert(0, str(ASSETLIB.parent))
from assetlib.tools.env import discover_blender  # noqa: E402
from assetlib.tools.run_p2_contract import (  # noqa: E402
    CONTRACT_SCENARIOS, _ensure_samples, _job, check_scenario, run_job_host,
)

def _blender_or_skip():
    try:
        return discover_blender()
    except FileNotFoundError:
        pytest.skip("Blender 4.2 LTS not installed")


def test_scenarios_table_is_the_contract():
    """The milestone runner and the tests share one table."""
    assert len(CONTRACT_SCENARIOS) >= 5
    ids = [s["id"] for s in CONTRACT_SCENARIOS]
    assert len(ids) == len(set(ids))
    assert {"fbx_roundtrip", "glb_roundtrip", "obj_to_both",
            "error_missing_source"} <= set(ids)


@pytest.mark.parametrize("scn", CONTRACT_SCENARIOS,
                         ids=[s["id"] for s in CONTRACT_SCENARIOS])
def test_convert_scenario(scn, tmp_path):
    blender = _blender_or_skip()
    _ensure_samples()
    job = _job(scn, work_root=tmp_path)
    result = run_job_host(job, blender=blender, work_root=tmp_path)
    passed, fails = check_scenario(scn, result)
    assert passed, "; ".join(fails or ["scenario failed"])
    if scn["expect"].get("ok"):
        # Validation JSON must itself be well-formed and consistent.
        val_file = (result.get("outputs") or {}).get("validation_file")
        assert val_file and Path(val_file).exists()
        import json

        on_disk = json.loads(Path(val_file).read_text(encoding="utf-8"))
        assert on_disk["asset"] == (result.get("outputs") or {}).get("name")


def test_error_cases_surface_structured_codes(tmp_path):
    """Boundary cases return structured codes, not tracebacks."""
    blender = _blender_or_skip()
    for scn in CONTRACT_SCENARIOS:
        if scn["expect"].get("ok", True):
            continue
        job = _job(scn, work_root=tmp_path)
        result = run_job_host(job, blender=blender, work_root=tmp_path)
        passed, _fails = check_scenario(scn, result)
        assert passed
        assert result.get("code") is not None or not result.get("ok")
        assert "Traceback" not in (result.get("log_tail") or "")
