"""Evidence-driven corrective retry engine.

The engine is deliberately repository-agnostic.  The staging callback owns
Stage 7.2 atomicity; this module only coordinates attempts and retains concise
failure evidence for a coding model or a deterministic test double.
"""
from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterable


@dataclass(slots=True)
class ValidationEvidence:
    command: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    changed_files: list[str] = field(default_factory=list)
    plan_summary: str = ""
    attempt: int = 0
    classification: str = "unknown"

    def concise(self, limit: int = 4000) -> dict[str, Any]:
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": _tail(self.stdout, limit // 3),
            "stderr": _tail(self.stderr, limit // 2),
            "changed_files": self.changed_files[:100],
            "plan_summary": _tail(self.plan_summary, 800),
            "attempt": self.attempt,
            "classification": self.classification,
        }


@dataclass(slots=True)
class RetryReport:
    passed: bool
    attempts: list[dict[str, Any]]
    final_evidence: dict[str, Any] | None = None


def _tail(text: str, limit: int) -> str:
    text = str(text or "")
    if len(text) <= limit:
        return text
    return "…" + text[-limit:]


def classify_failure(evidence: ValidationEvidence) -> str:
    text = f"{evidence.command} {evidence.stdout} {evidence.stderr}".lower()
    if evidence.exit_code == 124 or "timed out" in text or "timeout" in text:
        return "timeout"
    if "syntaxerror" in text or "parse error" in text:
        return "syntax"
    if "assert" in text or "failed" in text or "test" in text:
        return "test_failure"
    if "permission" in text or "denied" in text:
        return "permission"
    return "command_failure"


class RetryEngine:
    def __init__(self, max_retries: int = 3):
        self.max_retries = max(0, int(max_retries))

    def run(
        self,
        *,
        initial_plan: Any,
        stage: Callable[[Any, int], Any],
        validate: Callable[[Any, int], Any],
        corrective_plan: Callable[[Any, ValidationEvidence, int], Any],
        restore: Callable[[], None],
    ) -> RetryReport:
        plan = initial_plan
        attempts: list[dict[str, Any]] = []
        for attempt in range(1, self.max_retries + 2):
            staged = False
            try:
                stage(plan, attempt)
                staged = True
                raw = validate(plan, attempt)
                evidence = _coerce_evidence(raw, attempt, plan)
                if evidence.exit_code == 0:
                    record = {"attempt": attempt, "status": "PASS", "evidence": evidence.concise()}
                    attempts.append(record)
                    return RetryReport(True, attempts, evidence.concise())
                evidence.classification = classify_failure(evidence)
                attempts.append({"attempt": attempt, "status": "FAIL", "evidence": evidence.concise()})
                if attempt > self.max_retries:
                    restore()
                    return RetryReport(False, attempts, evidence.concise())
                # Each corrective plan is incremental and receives only the
                # concise, classified evidence rather than a giant log.
                plan = corrective_plan(plan, evidence, attempt)
            except Exception as exc:
                evidence = ValidationEvidence(
                    command="retry-engine",
                    exit_code=1,
                    stderr=f"{type(exc).__name__}: {exc}",
                    plan_summary=str(initial_plan),
                    changed_files=[], attempt=attempt,
                )
                evidence.classification = classify_failure(evidence)
                attempts.append({"attempt": attempt, "status": "ERROR", "evidence": evidence.concise()})
                restore()
                return RetryReport(False, attempts, evidence.concise())
        restore()
        return RetryReport(False, attempts, None)


def _coerce_evidence(raw: Any, attempt: int, plan: Any) -> ValidationEvidence:
    if isinstance(raw, ValidationEvidence):
        raw.attempt = attempt
        if not raw.plan_summary:
            raw.plan_summary = str(plan)
        return raw
    payload = raw if isinstance(raw, dict) else {"exit_code": int(raw or 1)}
    return ValidationEvidence(
        command=str(payload.get("command") or "validation"),
        exit_code=int(payload.get("exit_code", payload.get("exit", 1))),
        stdout=str(payload.get("stdout") or payload.get("out") or ""),
        stderr=str(payload.get("stderr") or payload.get("err") or ""),
        changed_files=[str(x) for x in payload.get("changed_files", [])],
        plan_summary=str(payload.get("plan_summary") or plan),
        attempt=attempt,
    )
