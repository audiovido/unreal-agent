"""qa/model.py — durable state model for the Aivido autonomous QA bot.

QARun / QACheck / QADefect are plain dataclasses persisted as JSON under
memory/qa/runs/{run_id}/. Every PASS must carry a verifier name; every
defect must carry severity, reproduction, expected/actual and evidence.

Statuses: PENDING RUNNING PASS FAIL BLOCKED SKIPPED
Severity: CRITICAL MAJOR MINOR WARNING
Defect ledger statuses: OPEN FIXED VERIFIED WONT_FIX BLOCKED
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNS_DIR = ROOT / "memory" / "qa" / "runs"
REPORTS_DIR = ROOT / "reports" / "qa"

# --- enums -------------------------------------------------------------------
STATUS_PENDING = "PENDING"
STATUS_RUNNING = "RUNNING"
STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_BLOCKED = "BLOCKED"
STATUS_SKIPPED = "SKIPPED"
TERMINAL_STATUSES = {STATUS_PASS, STATUS_FAIL, STATUS_BLOCKED, STATUS_SKIPPED}

SEV_CRITICAL = "CRITICAL"
SEV_MAJOR = "MAJOR"
SEV_MINOR = "MINOR"
SEV_WARNING = "WARNING"
SEVERITIES = (SEV_CRITICAL, SEV_MAJOR, SEV_MINOR, SEV_WARNING)

LEDGER_OPEN = "OPEN"
LEDGER_FIXED = "FIXED"
LEDGER_VERIFIED = "VERIFIED"
LEDGER_WONT_FIX = "WONT_FIX"
LEDGER_BLOCKED = "BLOCKED"

VERDICT_RELEASE_READY = "RELEASE_READY"
VERDICT_NOT_READY = "NOT_READY"
VERDICT_BLOCKED = "BLOCKED"

_state_lock = threading.RLock()


def new_run_id() -> str:
    return f"qar_{uuid.uuid4().hex[:12]}"


def _atomic_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    tmp.replace(path)


# --- data classes -------------------------------------------------------------


class QACheck:
    def __init__(
        self,
        name: str,
        category: str,
        *,
        expected: Any = None,
        severity_if_failed: str = SEV_MAJOR,
        verifier: str = "",
        detail: str = "",
    ) -> None:
        self.name = name
        self.category = category
        self.status = STATUS_PENDING
        self.duration = 0.0
        self.expected = expected
        self.observed: Any = None
        self.verifier = verifier
        self.evidence: List[str] = []
        self.severity_if_failed = severity_if_failed
        self.detail = detail

    def mark(self, status: str, observed: Any = None, detail: str = "",
             evidence: Optional[List[str]] = None) -> "QACheck":
        self.status = status
        if observed is not None:
            self.observed = observed
        if detail:
            self.detail = detail
        for e in (evidence or []):
            if e and e not in self.evidence:
                self.evidence.append(e)
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "status": self.status,
            "duration": round(self.duration, 3),
            "expected": self.expected,
            "observed": self.observed,
            "verifier": self.verifier,
            "evidence": list(self.evidence),
            "severity_if_failed": self.severity_if_failed,
            "detail": self.detail,
        }


class QADefect:
    def __init__(
        self,
        severity: str,
        title: str,
        category: str,
        *,
        reproduction: str = "",
        expected: str = "",
        actual: str = "",
        evidence: Optional[List[str]] = None,
        suspected_component: str = "",
        retryable: bool = False,
        blocker: bool = False,
        check_name: str = "",
        defect_id: Optional[str] = None,
    ) -> None:
        self.id = defect_id or f"QA-{uuid.uuid4().hex[:6].upper()}"
        self.severity = severity
        self.title = title
        self.category = category
        self.reproduction = reproduction
        self.expected = expected
        self.actual = actual
        self.evidence = list(evidence or [])
        self.suspected_component = suspected_component
        self.retryable = retryable
        self.blocker = blocker
        self.check_name = check_name
        self.status = LEDGER_OPEN
        self.created_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "severity": self.severity,
            "category": self.category,
            "title": self.title,
            "reproduction": self.reproduction,
            "expected": self.expected,
            "actual": self.actual,
            "evidence": list(self.evidence),
            "suspected_component": self.suspected_component,
            "retryable": self.retryable,
            "blocker": self.blocker,
            "check_name": self.check_name,
            "status": self.status,
            "created_at": round(self.created_at, 3),
        }


class QARun:
    """One durable autonomous QA run."""

    def __init__(self, run_id: Optional[str] = None, target: str = "") -> None:
        self.id = run_id or new_run_id()
        self.target = target or "Aivido V2 runtime"
        self.status = STATUS_PENDING
        self.started_at: Optional[float] = None
        self.finished_at: Optional[float] = None
        self.checks: List[QACheck] = []
        self.defects: List[QADefect] = []
        self.score: float = 0.0
        self.verdict: Optional[str] = None
        self.verdict_why: str = ""
        self.evidence: List[Dict[str, Any]] = []
        self.environment_snapshot: Dict[str, Any] = {}
        self.interrupted_note: str = ""

    # -- check helpers -----------------------------------------------------
    def add_check(self, check: QACheck) -> QACheck:
        self.checks.append(check)
        return check

    def check(self, name: str) -> Optional[QACheck]:
        for c in self.checks:
            if c.name == name:
                return c
        return None

    def record(self, check: QACheck, evidence: Optional[Dict[str, Any]] = None,
               evidence_paths: Optional[List[str]] = None) -> None:
        if evidence is not None:
            self.evidence.append({
                "check": check.name, "at": time.time(), **evidence})
        for p in (evidence_paths or []):
            check.evidence.append(str(p))
            self.evidence.append({"check": check.name, "path": str(p),
                                  "at": time.time()})

    def add_defect(self, defect: QADefect) -> QADefect:
        self.defects.append(defect)
        return defect

    # -- counters ----------------------------------------------------------
    def summary(self) -> Dict[str, int]:
        counts = {s: 0 for s in TERMINAL_STATUSES}
        for c in self.checks:
            counts[c.status] = counts.get(c.status, 0) + 1
        counts["total"] = len(self.checks)
        return counts

    def defects_by_severity(self) -> Dict[str, int]:
        out = {s: 0 for s in SEVERITIES}
        for d in self.defects:
            out[d.severity] = out.get(d.severity, 0) + 1
        return out

    def category_status(self) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for c in self.checks:
            if c.category not in out:
                out[c.category] = c.status
            elif c.status == STATUS_FAIL:
                out[c.category] = STATUS_FAIL
            elif c.status == STATUS_BLOCKED and out[c.category] != STATUS_FAIL:
                out[c.category] = STATUS_BLOCKED
        return out

    # -- persistence ---------------------------------------------------------
    @property
    def run_dir(self) -> Path:
        return DEFAULT_RUNS_DIR / self.id

    def save(self) -> None:
        with _state_lock:
            payload = self.to_dict()
            _atomic_write(self.run_dir / "run.json", payload)
            _atomic_write(self.run_dir / "checks.json", payload["checks"])
            _atomic_write(self.run_dir / "defects.json", payload["defects"])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "target": self.target,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "checks": [c.to_dict() for c in self.checks],
            "defects": [d.to_dict() for d in self.defects],
            "score": round(self.score, 2),
            "verdict": self.verdict,
            "verdict_why": self.verdict_why,
            "evidence": list(self.evidence),
            "environment_snapshot": self.environment_snapshot,
            "interrupted_note": self.interrupted_note,
            "summary": self.summary(),
            "defects_by_severity": self.defects_by_severity(),
            "category_status": self.category_status(),
        }

    @classmethod
    def load(cls, run_id: str) -> Optional["QARun"]:
        run_dir = DEFAULT_RUNS_DIR / run_id
        run_file = run_dir / "run.json"
        if not run_file.exists():
            return None
        try:
            data = json.loads(run_file.read_text(encoding="utf-8"))
        except Exception:
            return None
        run = cls(run_id=run_id, target=data.get("target", ""))
        run.status = data.get("status", STATUS_PENDING)
        run.started_at = data.get("started_at")
        run.finished_at = data.get("finished_at")
        run.score = float(data.get("score", 0.0))
        run.verdict = data.get("verdict")
        run.verdict_why = data.get("verdict_why", "")
        run.evidence = list(data.get("evidence", []))
        run.environment_snapshot = data.get("environment_snapshot", {})
        run.interrupted_note = data.get("interrupted_note", "")
        for cd in data.get("checks", []):
            check = QACheck(
                cd.get("name", ""), cd.get("category", ""),
                expected=cd.get("expected"),
                severity_if_failed=cd.get("severity_if_failed", SEV_MAJOR),
                verifier=cd.get("verifier", ""),
            )
            check.status = cd.get("status", STATUS_PENDING)
            check.duration = float(cd.get("duration", 0.0))
            check.observed = cd.get("observed")
            check.evidence = list(cd.get("evidence", []))
            check.detail = cd.get("detail", "")
            run.checks.append(check)
        for dd in data.get("defects", []):
            defect = QADefect(
                dd.get("severity", SEV_MINOR), dd.get("title", ""),
                dd.get("category", ""),
                reproduction=dd.get("reproduction", ""),
                expected=dd.get("expected", ""), actual=dd.get("actual", ""),
                evidence=dd.get("evidence", []),
                suspected_component=dd.get("suspected_component", ""),
                retryable=bool(dd.get("retryable")),
                blocker=bool(dd.get("blocker")),
                check_name=dd.get("check_name", ""),
                defect_id=dd.get("id"),
            )
            defect.status = dd.get("status", LEDGER_OPEN)
            defect.created_at = dd.get("created_at", time.time())
            run.defects.append(defect)
        return run

    @classmethod
    def list_ids(cls) -> List[str]:
        if not DEFAULT_RUNS_DIR.exists():
            return []
        ids = [p.name for p in DEFAULT_RUNS_DIR.iterdir()
               if p.is_dir() and (p / "run.json").exists()]
        return sorted(ids, reverse=True)

    @classmethod
    def recover_interrupted(cls) -> None:
        """Durable recovery: any run left in RUNNING/PENDING on disk is
        marked FAILED with an explicit interruption note (never silently
        dropped, never force-PASSed)."""
        with _state_lock:
            for run_id in cls.list_ids():
                run = cls.load(run_id)
                if run is None or run.status not in (
                        STATUS_RUNNING, STATUS_PENDING):
                    continue
                for c in run.checks:
                    if c.status == STATUS_RUNNING:
                        c.mark(STATUS_BLOCKED,
                               detail="interrupted by process restart",
                               observed={"error": "run interrupted"})
                run.status = STATUS_BLOCKED
                run.verdict = VERDICT_BLOCKED
                run.finished_at = time.time()
                run.interrupted_note = (
                    "Run interrupted before completion; marked BLOCKED on "
                    "recovery, never auto-PASSed.")
                run.save()


# --- module-level store helpers -------------------------------------------------


def latest_run() -> Optional[QARun]:
    ids = QARun.list_ids()
    if not ids:
        return None
    return QARun.load(ids[0])