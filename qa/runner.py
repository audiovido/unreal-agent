"""qa/runner.py — autonomous QA run orchestrator.

Runs the 10-group check matrix against the LIVE product runtime, records
real evidence, promotes failures to ledger defects, computes the release
verdict and writes the durable reports. Self-heal is bounded: one retry of
an idempotent request, status refresh, evidence re-query — never forced
PASS, never mutation of certified content.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

from qa import checks as checks_mod
from qa.client import BackendClient, BridgeProbe, environment_snapshot
from qa.ledger import merge_run_defects, reconcile_ledger
from qa.model import (
    STATUS_PENDING, STATUS_RUNNING, STATUS_PASS, STATUS_FAIL, QARun,
    new_run_id,
)
from qa.verdict import (
    compute_verdict, render_json_report, render_md_report,
)

_RUN_THREADS: Dict[str, threading.Thread] = {}
_LAST_ERROR: Dict[str, str] = {}


def start_run(target: str = "Aivido V2 runtime") -> QARun:
    """Create and persist a new QA run; launch it in the background."""
    run = QARun(run_id=new_run_id(), target=target)
    run.status = STATUS_RUNNING
    run.started_at = time.time()
    run.environment_snapshot = environment_snapshot()
    run.save()

    def worker() -> None:
        try:
            execute_run(run.id)
        except Exception as exc:
            _LAST_ERROR[run.id] = f"{type(exc).__name__}: {exc}"
            current = QARun.load(run.id)
            if current is not None:
                current.status = STATUS_FAIL
                current.finished_at = time.time()
                current.save()

    t = threading.Thread(target=worker, name=f"qa-run-{run.id}", daemon=True)
    _RUN_THREADS[run.id] = t
    t.start()
    return run


def execute_run(run_id: str) -> Dict[str, Any]:
    """Run the full matrix synchronously for a durable run id."""
    run = QARun.load(run_id)
    if run is None:
        raise ValueError(f"unknown run {run_id}")
    if run.status == STATUS_RUNNING and run.started_at:
        run.started_at = run.started_at or time.time()
    client = BackendClient()
    probe = BridgeProbe()

    # ORDER MATTERS: the black-box missions populate evidence that the
    # integrity group verifies, so missions run before evidence checks.
    checks_mod.run_runtime_health(run, client, probe)
    checks_mod.run_api_contract(run, client)
    checks_mod.run_mission_blackbox(run, client)
    checks_mod.run_false_pass_defense(run, client)
    checks_mod.run_evidence_integrity(run, client)
    checks_mod.run_unreal_state_safety(run, probe)
    checks_mod.run_cinematic_artifact(run)
    checks_mod.run_ui_blackbox(run, client)
    checks_mod.run_recovery(run, client)
    checks_mod.run_release_safety(run)

    # Score: percentage of checks PASS (SKIPPED neutral; BLOCKED excluded
    # from numerator, counted in denominator only as non-pass).
    summary = run.summary()
    total = max(1, summary["total"])
    score = round(100.0 * summary[STATUS_PASS] / total, 2)
    run.score = score
    if not run.started_at:
        run.started_at = time.time()

    verdict = compute_verdict(run)
    run.finished_at = time.time()
    run.status = "COMPLETED"
    run.save()

    render_json_report(run, verdict)
    render_md_report(run, verdict)
    merge_run_defects(run.defects, run_id=run.id)
    # Self-heal of the ledger: prior OPEN defects whose check now passes in
    # this run are marked VERIFIED with independent evidence — history is
    # never deleted, and only genuinely-reproducing defects stay OPEN.
    reconcile_ledger(run_id=run.id, checks=run.checks,
                     current_run_defects=run.defects)
    return run.to_dict()


def run_qa_sync(target: str = "Aivido V2 runtime") -> Dict[str, Any]:
    """Synchronous entry (used by CLI/tests)."""
    run = QARun(run_id=new_run_id(), target=target)
    run.status = STATUS_RUNNING
    run.started_at = time.time()
    run.environment_snapshot = environment_snapshot()
    run.save()
    return execute_run(run.id)


def is_running(run_id: str) -> bool:
    t = _RUN_THREADS.get(run_id)
    return bool(t and t.is_alive())


if __name__ == "__main__":
    import json
    result = run_qa_sync()
    print(json.dumps({
        "run_id": result["id"],
        "verdict": result["verdict"],
        "summary": result["summary"],
        "defects_by_severity": result["defects_by_severity"],
    }, indent=2))