"""qa/verdict.py — autonomous release verdict + report generation.

RELEASE_READY only when:
  - 0 CRITICAL open, 0 MAJOR open
  - core black-box mission PASS (readonly_diagnostic_mission + code task)
  - false-pass defense PASS
  - Unreal preservation PASS
  - evidence integrity PASS
  - full regression acceptable
Warnings/minors may remain but MUST be listed.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from qa.model import (
    SEV_CRITICAL, SEV_MAJOR, SEV_MINOR, SEV_WARNING,
    STATUS_PASS, STATUS_FAIL, STATUS_BLOCKED, STATUS_SKIPPED,
    VERDICT_RELEASE_READY, VERDICT_NOT_READY, VERDICT_BLOCKED,
    QARun, REPORTS_DIR,
)

REPORT_MD = REPORTS_DIR / "AIVIDO_V2_AUTONOMOUS_QA_REPORT.md"
REPORT_JSON = REPORTS_DIR / "AIVIDO_V2_AUTONOMOUS_QA.json"

# Groups whose PASS is mandatory for RELEASE_READY.
GATE_GROUPS = {
    "MISSION_BLACKBOX": "core black-box mission",
    "FALSE_PASS_DEFENSE": "false-pass defense",
    "UNREAL_STATE_SAFETY": "Unreal preservation",
    "EVIDENCE_INTEGRITY": "evidence integrity",
}

# Checks within MISSION_BLACKBOX that constitute the "core" mission PASS.
CORE_MISSION_CHECKS = ("readonly_diagnostic_mission", "code_task_pipeline")


def _category_checks(run: QARun, category: str) -> List[Any]:
    return [c for c in run.checks if c.category == category]


def _group_failed(run: QARun, group: str) -> List[str]:
    """A group FAIL only counts check failures that carry a release-gating
    severity (CRITICAL/MAJOR). MINOR/WARNING findings are recorded and
    listed but do not fail the group gate."""
    failed = []
    for c in _category_checks(run, group):
        if c.status == STATUS_FAIL and c.severity_if_failed in (
                SEV_CRITICAL, SEV_MAJOR):
            failed.append(c.name)
    return failed


def compute_verdict(run: QARun,
                    regression_ok: bool = True) -> Dict[str, Any]:
    defects = run.defects
    open_defects = [d for d in defects]
    critical_open = [d for d in open_defects
                     if d.severity == SEV_CRITICAL]
    major_open = [d for d in open_defects if d.severity == SEV_MAJOR]
    minor_open = [d for d in open_defects if d.severity == SEV_MINOR]
    warnings = [d for d in open_defects if d.severity == SEV_WARNING]

    # Core black-box mission: read-only mission + code task must PASS.
    core_mission_ok = True
    core_failures = []
    for name in CORE_MISSION_CHECKS:
        c = run.check(name)
        if c is None or c.status != STATUS_PASS:
            core_mission_ok = False
            core_failures.append(name)

    gate_results: Dict[str, bool] = {}
    gate_details: Dict[str, List[str]] = {}
    for group, label in GATE_GROUPS.items():
        failed = _group_failed(run, group)
        gate_results[label] = not failed
        gate_details[label] = failed

    blocked = run.status == STATUS_BLOCKED
    reasons: List[str] = []
    if blocked:
        reasons.append("run was interrupted/blocked before completion")
    if critical_open:
        reasons.append(f"{len(critical_open)} CRITICAL defect(s) open")
    if major_open:
        reasons.append(f"{len(major_open)} MAJOR defect(s) open")
    if not core_mission_ok:
        reasons.append("core black-box mission FAIL: "
                       + ", ".join(core_failures))
    for label, ok in gate_results.items():
        if not ok:
            reasons.append(f"{label} group FAIL"
                           + (f": {', '.join(gate_details[label])}" if
                              gate_details[label] else ""))
    if not regression_ok:
        reasons.append("full regression not acceptable")

    ready = (not blocked and not critical_open and not major_open
             and core_mission_ok and all(gate_results.values())
             and regression_ok)

    verdict = VERDICT_RELEASE_READY if ready else (
        VERDICT_NOT_READY if not blocked else VERDICT_BLOCKED)

    run.verdict = verdict
    run.verdict_why = ("RELEASE_READY: no open CRITICAL/MAJOR defects, core "
                       "mission PASS, false-pass defense PASS, Unreal "
                       "preservation PASS, evidence integrity PASS, "
                       "regression acceptable." if ready else
                       "NOT_READY: " + "; ".join(reasons))
    run.save()
    return {
        "verdict": verdict,
        "ready": ready,
        "blocked": blocked,
        "reasons": reasons,
        "counts": {
            "critical_open": len(critical_open),
            "major_open": len(major_open),
            "minor_open": len(minor_open),
            "warnings": len(warnings),
        },
        "core_mission_ok": core_mission_ok,
        "core_failures": core_failures,
        "gate_results": gate_results,
        "gate_details": gate_details,
        "regression_ok": regression_ok,
    }


def render_json_report(run: QARun, verdict: Dict[str, Any]) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "aivido.v2.autonomous-qa.v1",
        "run_id": run.id,
        "target": run.target,
        "status": run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "duration_s": round((run.finished_at or time.time()) -
                            (run.started_at or time.time()), 2),
        "score": run.score,
        "verdict": verdict["verdict"],
        "verdict_why": run.verdict_why,
        "reasons": verdict["reasons"],
        "counts": verdict["counts"],
        "summary": run.summary(),
        "defects_by_severity": run.defects_by_severity(),
        "category_status": run.category_status(),
        "gate_results": verdict["gate_results"],
        "gate_details": verdict["gate_details"],
        "core_mission_ok": verdict["core_mission_ok"],
        "environment_snapshot": run.environment_snapshot,
        "checks": [c.to_dict() for c in run.checks],
        "defects": [d.to_dict() for d in run.defects],
        "evidence": run.evidence,
    }
    tmp = REPORT_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False,
                              default=str), encoding="utf-8")
    tmp.replace(REPORT_JSON)
    return REPORT_JSON


def render_md_report(run: QARun, verdict: Dict[str, Any]) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    lines.append("# AIVIDO V2 — AUTONOMOUS QA REPORT")
    lines.append("")
    lines.append(f"- **Run ID:** `{run.id}`")
    lines.append(f"- **Target:** {run.target}")
    lines.append(f"- **Status:** {run.status}")
    lines.append(f"- **Started:** {_ts(run.started_at)}")
    lines.append(f"- **Finished:** {_ts(run.finished_at)}")
    lines.append(f"- **Duration:** {_dur(run)}s")
    lines.append(f"- **Score:** {run.score:.2f}/100")
    lines.append("")
    lines.append(f"## VERDICT: **{verdict['verdict']}**")
    lines.append("")
    lines.append(f"{run.verdict_why}")
    lines.append("")
    lines.append("### Summary")
    s = run.summary()
    lines.append(f"Total checks **{s['total']}**: PASS **{s['PASS']}** | "
                 f"FAIL **{s['FAIL']}** | BLOCKED **{s['BLOCKED']}** | "
                 f"SKIPPED **{s['SKIPPED']}**")
    db = run.defects_by_severity()
    lines.append(f"Defects: CRITICAL **{db['CRITICAL']}** | MAJOR "
                 f"**{db['MAJOR']}** | MINOR **{db['MINOR']}** | WARNING "
                 f"**{db['WARNING']}**")
    lines.append("")
    lines.append("### Group Results")
    lines.append("")
    lines.append("| Group | Status |")
    lines.append("|---|---|")
    for group, status in run.category_status().items():
        lines.append(f"| {group} | {status} |")
    lines.append("")
    if verdict["gate_results"]:
        lines.append("### Release Gates")
        lines.append("")
        for label, ok in verdict["gate_results"].items():
            detail = verdict["gate_details"].get(label, [])
            lines.append(f"- **{label}**: {'PASS' if ok else 'FAIL'}"
                         + (f" ({', '.join(detail)})" if detail else ""))
        lines.append("")
    lines.append("### Open Defects (ledger)")
    lines.append("")
    if run.defects:
        lines.append("| ID | Severity | Category | Title |")
        lines.append("|---|---|---|---|")
        for d in run.defects:
            lines.append(f"| {d.id} | {d.severity} | {d.category} | "
                         f"{d.title.replace('|', '/')} |")
    else:
        lines.append("_No open defects recorded._")
    lines.append("")
    lines.append("### Checks")
    lines.append("")
    for c in run.checks:
        lines.append(f"- `[{c.status}]` **{c.name}** ({c.category}) — "
                     f"{c.detail}")
        if c.verifier:
            lines.append(f"  - verifier: `{c.verifier}`")
        if c.evidence:
            lines.append(f"  - evidence: {', '.join(c.evidence[:4])}")
    lines.append("")
    lines.append("---")
    lines.append(f"_Generated by the Aivido autonomous QA bot (run "
                 f"`{run.id}`) at {_ts(time.time())}._")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = REPORT_MD.with_suffix(".md.tmp")
    tmp.write_text("\n".join(lines), encoding="utf-8")
    tmp.replace(REPORT_MD)
    return REPORT_MD


def _ts(value: Optional[float]) -> str:
    if not value:
        return "—"
    return time.strftime("%Y-%m-%d %H:%M:%S",
                         time.localtime(value))


def _dur(run: QARun) -> float:
    if not run.started_at:
        return 0.0
    return round((run.finished_at or time.time()) - run.started_at, 2)