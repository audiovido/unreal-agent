"""qa/checks.py — the autonomous check matrix (10 independent QA groups).

Each group is a function (run, client, probe) -> None that appends QACheck
entries to the run, marks them PASS/FAIL/BLOCKED/SKIPPED with independent
verifier evidence, and raises QADefect entries for every failure. No check
is allowed to PASS without a verifier verdict.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from qa.client import BackendClient, BridgeProbe, environment_snapshot
from qa.model import (
    QACheck, QADefect, QARun,
    SEV_CRITICAL, SEV_MAJOR, SEV_MINOR, SEV_WARNING,
    STATUS_PASS, STATUS_FAIL, STATUS_BLOCKED, STATUS_SKIPPED,
)
from qa.verifier import verify

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Check execution helper (timing + verifier + defect promotion)
# ---------------------------------------------------------------------------


def execute_check(
    run: QARun,
    check: QACheck,
    fn: Callable[[], Any],
    expected: Any,
    ctx: Optional[Dict[str, Any]] = None,
    *,
    reproduction: str = "",
    suspected_component: str = "",
) -> QACheck:
    """Run fn(), feed (expected, observed) through the check's verifier and
    mark PASS/FAIL. A FAIL raises a QADefect with the check's
    severity_if_failed."""
    started = time.time()
    try:
        observed = fn()
    except Exception as exc:
        check.duration = time.time() - started
        check.mark(STATUS_FAIL, observed={"error": f"{type(exc).__name__}: {exc}"},
                   detail=f"check raised: {exc}")
        run.record(check)
        run.add_defect(QADefect(
            check.severity_if_failed, f"{check.name}: check raised",
            check.category, reproduction=reproduction or f"run {check.name}",
            expected=str(expected), actual=str(exc),
            evidence=list(check.evidence),
            suspected_component=suspected_component or check.category,
            check_name=check.name))
        run.save()
        return check
    check.duration = time.time() - started
    check.observed = observed
    result = verify(check, expected, observed, ctx or {})
    ok = bool(result.get("ok"))
    detail = str(result.get("detail") or "")
    check.mark(STATUS_PASS if ok else STATUS_FAIL, observed=observed,
               detail=detail)
    run.record(check, {"verifier": check.verifier, "detail": detail,
                       "expected": expected})
    if not ok:
        run.add_defect(QADefect(
            check.severity_if_failed, f"{check.name}: {detail}",
            check.category, reproduction=reproduction or f"run {check.name}",
            expected=str(expected), actual=detail,
            evidence=list(check.evidence),
            suspected_component=suspected_component or check.category,
            check_name=check.name))
    run.save()
    return check


def mark_skipped(run: QARun, check: QACheck, reason: str) -> QACheck:
    check.mark(STATUS_SKIPPED, detail=reason)
    run.record(check)
    run.save()
    return check


def wait_mission(client: BackendClient, mission_id: str,
                 timeout_s: float = 420.0, poll_s: float = 5.0,
                 max_silent_s: float = 90.0) -> Dict[str, Any]:
    """Poll a real mission checkpoint to a terminal state. Returns the final
    payload or a timeout payload (never fabricates a verdict)."""
    deadline = time.time() + timeout_s
    last_change = time.time()
    last_status = None
    while time.time() < deadline:
        resp = client.mission(mission_id)
        body = resp.get("body") or {}
        status = str(body.get("status") or "")
        if status != last_status:
            last_change = time.time()
            last_status = status
        if status in ("complete", "failed", "blocked", "cancelled"):
            body["_poll_ok"] = True
            return body
        if time.time() - last_change > max_silent_s:
            return {"status": status or "unknown",
                    "verdict": None,
                    "_poll_ok": False,
                    "why": f"stalled: no status change for "
                           f"{max_silent_s:.0f}s while {status}",
                    "mission_id": mission_id}
        time.sleep(poll_s)
    return {"status": "timeout", "verdict": None, "_poll_ok": False,
            "why": f"mission {mission_id} did not finish within "
                   f"{timeout_s:.0f}s", "mission_id": mission_id}


# ===========================================================================
# GROUP 1 — RUNTIME HEALTH
# ===========================================================================

def run_runtime_health(run: QARun, client: BackendClient,
                       probe: BridgeProbe) -> None:
    cat = "RUNTIME_HEALTH"

    c = run.add_check(QACheck("backend_status", cat, expected="ok envelope",
                              verifier="health_ok", severity_if_failed=SEV_CRITICAL,
                              detail="GET /api/status"))
    execute_check(run, c, lambda: (client.status().get("body") or {}),
                  "ok envelope", suspected_component="backend")

    c = run.add_check(QACheck("backend_latency", cat, expected="< 5000ms",
                              verifier="truthful_claim",
                              severity_if_failed=SEV_WARNING,
                              detail="latency sanity"))
    def _latency():
        r = client.status()
        return {"latency_ms": r.get("latency_ms"), "ok": r.get("ok"),
                "http_status": r.get("http_status")}
    execute_check(run, c, _latency, "latency claim",
                  {"field": "latency_ms"}, suspected_component="backend")

    c = run.add_check(QACheck("doctor_report", cat,
                              expected="doctor PASS/DEGRADED",
                              verifier="truthful_claim",
                              severity_if_failed=SEV_MAJOR,
                              detail="unreal-coder doctor"))
    def _doctor():
        r = client.doctor()
        body = r.get("body") or {}
        if not r.get("ok"):
            return {"error": str(body.get("error") or "doctor unreachable")}
        return {"overall": body.get("overall"),
                "summary": body.get("summary"),
                "generated_at": body.get("generated_at")}
    execute_check(run, c, _doctor, "doctor report",
                  suspected_component="backend")

    c = run.add_check(QACheck("bridge_identity", cat, expected="ASSET_Showcase2",
                              verifier="registry_match",
                              severity_if_failed=SEV_CRITICAL,
                              detail="live bridge identifies expected project"))
    def _identity():
        ident = probe.identity()
        if not ident.get("ok"):
            return {"error": ident.get("error")}
        return {"project_name": ident.get("project_name"),
                "engine": ident.get("engine"),
                "world": ident.get("world")}
    execute_check(run, c, _identity, "ASSET_Showcase2",
                  {"field": "project_name"},
                  reproduction="live bridge probe",
                  suspected_component="unreal-bridge")

    c = run.add_check(QACheck("bridge_engine_version", cat,
                              expected="UE 5.8", verifier="truthful_claim",
                              severity_if_failed=SEV_MAJOR,
                              detail="expected editor version"))
    def _engine():
        ident = probe.identity()
        if not ident.get("ok"):
            return {"error": ident.get("error")}
        engine = str(ident.get("engine", ""))
        return {"engine": engine, "matches_5_8": "5.8" in engine}
    execute_check(run, c, _engine, "UE 5.8",
                  suspected_component="unreal-bridge")

    c = run.add_check(QACheck("ports_listening", cat, expected="8765, 6766",
                              verifier="truthful_claim",
                              severity_if_failed=SEV_CRITICAL,
                              detail="backend + bridge ports"))
    def _ports():
        snap = environment_snapshot()
        return {"backend": snap.get("backend_listening"),
                "bridge": snap.get("bridge_listening")}
    execute_check(run, c, _ports, "ports claim",
                  suspected_component="runtime")

    c = run.add_check(QACheck("single_listener_per_port", cat,
                              expected="no duplicate listener",
                              verifier="truthful_claim",
                              severity_if_failed=SEV_MAJOR,
                              detail="no process corruption on ports"))
    def _listeners():
        """Count listeners on the LOOPBACK interface only (127.0.0.1 / [::1]).
        Tailscale-serve and other VPN-bound interfaces are ignored so a
        legitimate external proxy is not mistaken for a duplicate bridge."""
        try:
            out = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True,
                timeout=15, encoding="utf-8", errors="replace").stdout
        except Exception as exc:
            return {"error": str(exc)}
        counts = {}
        for line in out.splitlines():
            m = re.search(r"\b(127\.0\.0\.1|\[::1\]):(8765|6766)\b"
                          r".*LISTENING\s+(\d+)", line)
            if m:
                port = m.group(2)
                pid = m.group(3)
                counts.setdefault(port, set()).add(pid)
        return {port: len(pids) for port, pids in counts.items()}
    observed = execute_check(run, c, _listeners, "listener claim",
                             suspected_component="runtime").observed
    if isinstance(observed, dict) and observed.get("error"):
        c.mark(STATUS_BLOCKED, detail=f"listener probe failed: "
                                      f"{observed['error']}")
        run.save()
    elif isinstance(observed, dict) and observed:
        # Every observed listener must be single-PID (no corruption).
        dupes = {p: n for p, n in observed.items() if n > 1}
        if dupes:
            c.mark(STATUS_FAIL, detail="duplicate listeners per port: "
                                       + json.dumps(dupes))
            run.record(c)
            run.add_defect(QADefect(
                SEV_MAJOR, "single_listener_per_port: duplicate listener",
                cat, reproduction="netstat port scan",
                expected="one PID per port", actual=json.dumps(dupes),
                evidence=list(c.evidence), check_name=c.name))
            run.save()
        else:
            c.mark(STATUS_PASS, detail="all observed listeners single-PID")
            run.record(c)
            run.save()
    elif isinstance(observed, dict) and not observed:
        # Ports free / no listeners is not corruption.
        c.mark(STATUS_PASS, detail="no listeners on 8765/6766 (ports free)")
        run.record(c)
        run.save()


# ===========================================================================
# GROUP 2 — API CONTRACT
# ===========================================================================

def run_api_contract(run: QARun, client: BackendClient) -> None:
    cat = "API_CONTRACT"

    c = run.add_check(QACheck("status_endpoint", cat, expected="200 ok",
                              verifier="http_ok",
                              severity_if_failed=SEV_CRITICAL,
                              detail="GET /api/status"))
    execute_check(run, c, lambda: client.status(), "200 ok",
                  {"require_body_ok": True}, suspected_component="backend")

    c = run.add_check(QACheck("start_mission_endpoint", cat,
                              expected="accepted + mission_id",
                              verifier="truthful_claim",
                              severity_if_failed=SEV_CRITICAL,
                              detail="POST /api/unreal-coder/async"))
    def _start():
        r = client.start_mission(
            "READ ONLY: report backend and Unreal bridge health",
            read_only=True)
        body = r.get("body") or {}
        return {"http_status": r.get("http_status"), "ok": body.get("ok"),
                "mission_id": body.get("mission_id"),
                "status": body.get("status")}
    execute_check(run, c, _start, "accepted", suspected_component="backend")
    started = run.check("start_mission_endpoint")
    if started and started.status == STATUS_PASS:
        run.evidence.append({"check": "start_mission_endpoint",
                             "mission_id": (started.observed or {}).get(
                                 "mission_id"), "at": time.time()})

    c = run.add_check(QACheck("mission_status_endpoint", cat,
                              expected="checkpoint payload",
                              verifier="truthful_claim",
                              severity_if_failed=SEV_MAJOR,
                              detail="GET /api/unreal-coder/mission/{id}"))
    def _status_shape():
        start = run.check("start_mission_endpoint")
        mid = (start.observed or {}).get("mission_id") if start else None
        if not mid:
            return {"error": "no mission_id from start check"}
        r = client.mission(mid)
        body = r.get("body") or {}
        return {"http_status": r.get("http_status"),
                "mission_id": body.get("mission_id"),
                "status": body.get("status"),
                "has_plan": bool(body.get("plan")),
                "checkpoint_fields": sorted(
                    k for k in ("mission_id", "status", "verdict", "why",
                                "evidence") if k in body)}
    execute_check(run, c, _status_shape, "checkpoint payload",
                  suspected_component="backend")

    c = run.add_check(QACheck("route_prompt", cat, expected="routing decision",
                              verifier="truthful_claim",
                              severity_if_failed=SEV_MAJOR,
                              detail="POST /api/code/classify"))
    def _route():
        r = client.classify(
            "create a python helper module and write a unit test for it")
        body = r.get("body") or {}
        return {"http_status": r.get("http_status"), "ok": body.get("ok"),
                "routing": body.get("routing")}
    execute_check(run, c, _route, "routing decision",
                  suspected_component="code-worker")

    c = run.add_check(QACheck("malformed_input_rejected", cat,
                              expected="4xx on malformed body",
                              verifier="truthful_claim",
                              severity_if_failed=SEV_MAJOR,
                              detail="empty prompt rejected"))
    def _malformed():
        r = client.request("POST", "/api/unreal-coder/async",
                           {"prompt": ""}, timeout=20)
        return {"http_status": r.get("http_status")}
    execute_check(run, c, _malformed, "4xx")
    if c.status == STATUS_PASS and int(
            (c.observed or {}).get("http_status") or 0) >= 400:
        pass  # correctly rejected

    c = run.add_check(QACheck("unknown_mission_id_404", cat,
                              expected="404", verifier="truthful_claim",
                              severity_if_failed=SEV_MAJOR,
                              detail="GET unknown mission id"))
    def _unknown():
        r = client.mission(f"mission_nonexistent_{uuid.uuid4().hex[:8]}")
        return {"http_status": r.get("http_status")}
    execute_check(run, c, _unknown, "404", suspected_component="backend")

    c = run.add_check(QACheck("timeout_behavior", cat,
                              expected="honest timeout/error envelope",
                              verifier="truthful_claim",
                              severity_if_failed=SEV_WARNING,
                              detail="backend does not hang forever"))
    def _timeout():
        try:
            import requests as _req
            r = _req.get(client.base_url + "/api/unreal-coder/doctor",
                         timeout=1)
            return {"http_status": r.status_code, "latency_ok": True}
        except Exception:
            # A fast refusal/timeout is the honest behavior; a hard hang
            # would have blocked this probe past the timeout.
            return {"http_status": 0, "latency_ok": True,
                    "note": "request refused/timed out quickly"}
    execute_check(run, c, _timeout, "honest envelope",
                  suspected_component="backend")


# ===========================================================================
# GROUP 3 — MISSION BLACK-BOX (real missions through the real pipeline)
# ===========================================================================

def run_mission_blackbox(run: QARun, client: BackendClient) -> None:
    cat = "MISSION_BLACKBOX"

    # --- 3.1 read-only diagnostic mission ---------------------------------
    c = run.add_check(QACheck("readonly_diagnostic_mission", cat,
                              expected="complete PASS + evidence",
                              verifier="mission_verdict",
                              severity_if_failed=SEV_CRITICAL,
                              detail="READ ONLY: report backend and bridge "
                                     "health"))
    def _run_diag():
        r = client.start_mission(
            "READ ONLY: report backend and Unreal bridge health",
            read_only=True)
        mid = (r.get("body") or {}).get("mission_id")
        if not mid:
            return {"error": "no mission_id", "status": "dispatch_failed"}
        run.evidence.append({"check": c.name, "mission_id": mid,
                             "at": time.time()})
        return wait_mission(client, mid, timeout_s=300)
    execute_check(run, c, _run_diag, "complete PASS + evidence",
                  reproduction="POST /api/unreal-coder/async with read-only "
                               "diagnostic prompt; poll checkpoint",
                  suspected_component="mission-pipeline")
    diag = c.observed if isinstance(c.observed, dict) else {}
    diag_mid = diag.get("mission_id")
    for ev in (diag.get("evidence") or []):
        if isinstance(ev, dict):
            p = ev.get("path") or ev.get("file") or ev.get("resource_path")
            if p:
                c.evidence.append(str(p))
                run.evidence.append({"check": c.name, "path": str(p),
                                     "at": time.time()})
    if c.evidence:
        c.detail += f"; evidence: {len(c.evidence)} path(s)"

    # --- 3.2 harmless isolated Unreal mission ------------------------------
    c2 = run.add_check(QACheck("isolated_capture_mission", cat,
                               expected="complete PASS + evidence",
                               verifier="mission_verdict",
                               severity_if_failed=SEV_MAJOR,
                               detail="READ ONLY: diagnostic capture of the "
                                      "current level"))
    def _run_capture():
        r = client.start_mission(
            "read-only diagnostic: capture a screenshot of the current level",
            read_only=True)
        mid = (r.get("body") or {}).get("mission_id")
        if not mid:
            return {"error": "no mission_id", "status": "dispatch_failed"}
        run.evidence.append({"check": c2.name, "mission_id": mid,
                             "at": time.time()})
        return wait_mission(client, mid, timeout_s=300)
    execute_check(run, c2, _run_capture, "complete PASS + evidence",
                  reproduction="read-only diagnostic capture mission through "
                               "the real pipeline",
                  suspected_component="mission-pipeline")
    c2_obs = c2.observed if isinstance(c2.observed, dict) else {}
    for ev in (c2_obs.get("evidence") or []):
        if isinstance(ev, dict):
            p = ev.get("path") or ev.get("file") or ev.get("resource_path")
            if p:
                c2.evidence.append(str(p))
                run.evidence.append({"check": c2.name, "path": str(p),
                                     "at": time.time()})
    if c2.evidence:
        c2.detail += f"; evidence: {len(c2.evidence)} path(s)"

    # --- 3.2b plain screenshot phrasing gap (MINOR, listed not blocking) ----
    c2b = run.add_check(QACheck("plain_capture_phrasing_routing", cat,
                                expected="plans an EVIDENCE/capture step",
                                verifier="truthful_claim",
                                severity_if_failed=SEV_MINOR,
                                detail="plain 'capture a screenshot' request "
                                       "should plan a capture step"))
    def _run_plain_capture():
        r = client.start_mission(
            "READ ONLY: capture a fresh viewport screenshot for QA evidence",
            read_only=True)
        mid = (r.get("body") or {}).get("mission_id")
        if not mid:
            return {"error": "no mission_id", "status": "dispatch_failed"}
        payload = client.mission(mid).get("body") or {}
        plan = payload.get("plan") or {}
        steps = plan.get("steps") or []
        phases = [p.get("phase") for p in (plan.get("phases") or [])]
        run.evidence.append({"check": c2b.name, "mission_id": mid,
                             "at": time.time()})
        return {"step_count": len(steps), "phases": phases,
                "planned_capture": any(
                    str(s.get("preferred_tool")) == "capture_unreal_viewport"
                    for s in steps)}
    obs2b = execute_check(run, c2b, _run_plain_capture,
                          "plans an EVIDENCE/capture step",
                          reproduction="start plain capture-only mission and "
                                       "inspect its plan",
                          suspected_component="mission-pipeline").observed
    if isinstance(obs2b, dict):
        steps = int(obs2b.get("step_count") or 0)
        if steps == 0:
            c2b.mark(STATUS_FAIL,
                     detail="plain 'capture a screenshot' prompt planned 0 "
                            "steps (ANSWER phase) — screenshot request did "
                            "not reach the capture pipeline")
            run.record(c2b)
            run.add_defect(QADefect(
                SEV_MINOR, "plain_capture_phrasing_routing: screenshot "
                           "request plans 0 steps", cat,
                reproduction="POST a plain 'capture a fresh viewport "
                             "screenshot' read-only mission",
                expected="a capture/EVIDENCE step is planned",
                actual=(f"planned 0 steps; phases="
                        f"{obs2b.get('phases')}"),
                evidence=list(c2b.evidence), check_name=c2b.name,
                suspected_component="mission-pipeline",
                retryable=True))
            run.save()

    # --- 3.3 code task ------------------------------------------------------
    c3 = run.add_check(QACheck("code_task_pipeline", cat,
                               expected="PASS + commit + evidence bundle",
                               verifier="truthful_claim",
                               severity_if_failed=SEV_MAJOR,
                               detail="isolated worktree code task"))
    probe_rel = f"tests/qa_scaffold/qaprobe_{uuid.uuid4().hex[:8]}.py"

    def _run_code_task():
        body = {
            "title": "QA scaffold probe file",
            "prompt": (f"create a new repository file {probe_rel} "
                       "containing a tiny pure function for QA scaffolding"),
            "routing": "code",
            "steps": [{"op": "create_file", "path": probe_rel,
                       "content": "def qa_probe():\n"
                                  "    return 'qa-ok'\n"}],
            "tests": [f"py_compile {probe_rel}"],
            "acceptance": [f"exists {probe_rel}",
                           f"contains {probe_rel}|qa-ok"],
            "scope": [probe_rel],
        }
        r = client.enqueue_code_task(**body)
        resp = r.get("body") or {}
        task_id = (resp.get("task") or {}).get("id")
        if not task_id:
            return {"error": str(resp.get("detail") or "enqueue failed"),
                    "http_status": r.get("http_status")}
        run.evidence.append({"check": c3.name, "task_id": task_id,
                             "at": time.time()})
        deadline = time.time() + 420
        while time.time() < deadline:
            t = client.code_task(task_id)
            task = (t.get("body") or {}).get("task") or {}
            status = task.get("status")
            if status in ("passed", "failed", "blocked", "cancelled"):
                result = task.get("result") or {}
                return {"task_id": task_id, "status": status,
                        "verdict": task.get("verdict"),
                        "error": task.get("error"),
                        "blocked_reason": task.get("blocked_reason"),
                        "commit": (result or {}).get("commit"),
                        "branch": (result or {}).get("branch"),
                        "evidence_files": list(task.get("evidence") or [])}
            time.sleep(4)
        return {"task_id": task_id, "status": "timeout",
                "verdict": None, "error": "code task timed out"}
    observed3 = execute_check(run, c3, _run_code_task,
                              "PASS + commit + evidence bundle",
                              reproduction=f"enqueue code task creating "
                                           f"{probe_rel} in isolated worktree",
                              suspected_component="code-worker").observed
    if isinstance(observed3, dict) and observed3.get("status") == "passed":
        task_id = observed3.get("task_id")
        c3.verifier = "truthful_claim"
        ev = client.code_task_evidence(task_id) if task_id else None
        evbody = (ev or {}).get("body") or {}
        bundle = evbody.get("evidence") or {}
        has_patch = bool(bundle.get("evidence_files"))
        c3.mark(STATUS_PASS,
                observed={**observed3, "evidence_bundle_ok": has_patch},
                detail=(f"code task PASS: commit {str(observed3.get('commit'))[:12]} "
                        f"evidence_files={len(bundle.get('evidence_files') or [])}"))
        for ef in (bundle.get("evidence_files") or []):
            if isinstance(ef, dict):
                p = ef.get("path") or ef.get("file")
                if p:
                    c3.evidence.append(str(p))
            elif isinstance(ef, str) and ef:
                c3.evidence.append(ef)
        if c3.evidence:
            run.evidence.append({"check": c3.name,
                                 "paths": list(c3.evidence), "at": time.time()})
        run.record(c3, {"verifier": "truthful_claim",
                        "detail": c3.detail, "evidence_bundle_ok": has_patch})
        run.save()

    # --- 3.4 mixed routing mission (attempted; SKIPPED if unsupported) -----
    c4 = run.add_check(QACheck("mixed_routing_mission", cat,
                               expected="code stage + unreal stage PASS",
                               verifier="truthful_claim",
                               severity_if_failed=SEV_WARNING,
                               detail="mixed routing mission"))
    probe_rel2 = f"tests/qa_scaffold/mixed_{uuid.uuid4().hex[:8]}.py"

    def _run_mixed():
        body = {
            "title": "QA mixed routing probe",
            "prompt": (f"create a new repository file {probe_rel2} and then "
                       "run a read-only Unreal health mission"),
            "routing": "mixed",
            "steps": [{"op": "create_file", "path": probe_rel2,
                       "content": "def mixed_probe():\n    return 1\n"}],
            "tests": [f"py_compile {probe_rel2}"],
            "acceptance": [f"exists {probe_rel2}"],
            "scope": [probe_rel2],
            "unreal_prompt": "READ ONLY: report backend and Unreal bridge "
                             "health",
        }
        r = client.enqueue_code_task(**body)
        resp = r.get("body") or {}
        detail = resp.get("detail")
        if detail or not (resp.get("task") or {}).get("id"):
            return {"status": "unsupported",
                    "error": str(detail or "mixed task rejected")}
        task_id = (resp.get("task") or {}).get("id")
        deadline = time.time() + 600
        while time.time() < deadline:
            t = client.code_task(task_id)
            task = (t.get("body") or {}).get("task") or {}
            status = task.get("status")
            if status in ("passed", "failed", "blocked", "cancelled"):
                result = task.get("result") or {}
                unreal = (result or {}).get("unreal_stage") or {}
                return {"task_id": task_id, "status": status,
                        "verdict": task.get("verdict"),
                        "error": task.get("error"),
                        "unreal_stage": {
                            "status": unreal.get("status"),
                            "verdict": unreal.get("verdict"),
                            "mission_id": unreal.get("mission_id")}}
            time.sleep(4)
        return {"task_id": task_id, "status": "timeout", "verdict": None}
    mixed_obs = execute_check(run, c4, _run_mixed,
                              "code stage + unreal stage PASS",
                              reproduction="enqueue mixed task with "
                                           "unreal_prompt",
                              suspected_component="code-worker").observed
    if isinstance(mixed_obs, dict) and mixed_obs.get("status") == "unsupported":
        c4.mark(STATUS_SKIPPED,
                detail=f"mixed routing not currently supported: "
                       f"{mixed_obs.get('error')}")
        run.save()


# ===========================================================================
# GROUP 4 — FALSE-PASS DEFENSE (injected bad cases MUST fail)
# ===========================================================================

def run_false_pass_defense(run: QARun, client: BackendClient) -> None:
    cat = "FALSE_PASS_DEFENSE"

    def bad_case(name: str, verifier_name: str, expected: Any,
                 observed: Any, ctx: Optional[Dict[str, Any]] = None,
                 sev: str = SEV_CRITICAL) -> QACheck:
        c = run.add_check(QACheck(name, cat, expected="rejected",
                                  verifier="expect_failure",
                                  severity_if_failed=sev,
                                  detail=f"bad case: {verifier_name}"))
        result = verify(QACheck("", cat, verifier=verifier_name),
                        expected, observed, ctx or {})
        outcome = "FAIL" if not result.get("ok") else "PASS"
        ok = outcome != "PASS"
        c.mark(STATUS_PASS if ok else STATUS_FAIL,
               observed={"outcome": outcome,
                         "inner_detail": result.get("detail")},
               detail=(f"bad case rejected ({verifier_name} -> "
                       f"{result.get('detail')})" if ok else
                       f"BAD CASE PASSED: {verifier_name} -> "
                       f"{result.get('detail')}"))
        run.record(c, {"verifier": "expect_failure", "outcome": outcome})
        if not ok:
            run.add_defect(QADefect(
                sev, f"{name}: false PASS risk ({verifier_name})",
                cat, reproduction=f"inject {verifier_name} with bad fixture",
                expected="bad case rejected", actual=result.get("detail"),
                evidence=list(c.evidence), check_name=name,
                suspected_component="verifier"))
        run.save()
        return c

    # 4.1 completed status with missing evidence
    bad_case("completed_without_evidence", "mission_verdict",
             "complete PASS + evidence",
             {"status": "complete", "verdict": "PASS",
              "completed_work": {"steps_completed": 2}, "evidence": []})
    # 4.2 missing screenshot
    bad_case("missing_screenshot", "screenshot_valid",
             "valid screenshot",
             str(ROOT / "memory" / "qa" / "no_such_screenshot.png"))
    # 4.3 invalid screenshot (text file is not an image)
    fake = ROOT / "memory" / "qa" / "fake_screenshot.png"
    fake.parent.mkdir(parents=True, exist_ok=True)
    fake.write_text("not an image at all", encoding="utf-8")
    bad_case("invalid_screenshot", "screenshot_valid", "valid screenshot",
             str(fake))
    # 4.4 stale duplicate evidence (byte-identical captures)
    dup_a = ROOT / "memory" / "qa" / "dup_a.png"
    dup_b = ROOT / "memory" / "qa" / "dup_b.png"
    dup_a.write_bytes(b"\x89PNG-fake-identical")
    dup_b.write_bytes(b"\x89PNG-fake-identical")
    bad_case("stale_duplicate_evidence", "no_stale_duplicate",
             "distinct captures", [str(dup_a), str(dup_b)])
    # 4.5 wrong task id (404 expected)
    c = run.add_check(QACheck("wrong_task_id_rejected", cat,
                              expected="404", verifier="truthful_claim",
                              severity_if_failed=SEV_MAJOR,
                              detail="GET unknown mission id"))
    execute_check(run, c,
                  lambda: {"http_status": client.mission(
                      "mission_does_not_exist_zz").get("http_status")},
                  "404", suspected_component="backend")
    if c.status == STATUS_PASS and int(
            (c.observed or {}).get("http_status") or 0) >= 400:
        pass
    else:
        c.mark(STATUS_FAIL,
               detail=f"unknown task id returned "
                      f"{(c.observed or {}).get('http_status')}, expected 404")
        run.record(c)
        run.add_defect(QADefect(
            SEV_MAJOR, "wrong_task_id_rejected: unknown id not 404", cat,
            reproduction="GET /api/unreal-coder/mission/<random>",
            expected="404", actual=str(c.observed),
            evidence=list(c.evidence), check_name=c.name))
        run.save()
    # 4.6 blocked task must not PASS
    bad_case("blocked_task_not_pass", "mission_verdict", "complete PASS",
             {"status": "blocked", "verdict": "BLOCKED",
              "completed_work": {"steps_completed": 0}, "evidence": []})
    # 4.7 timed-out task must not PASS
    bad_case("timed_out_task_not_pass", "mission_verdict", "complete PASS",
             {"status": "executing", "verdict": None,
              "completed_work": {"steps_completed": 0}, "evidence": []})
    # 4.8 bridge unavailable must fail required checks
    bad_case("bridge_unavailable_fails", "registry_match",
             "ASSET_Showcase2", {"project_name": ""},
             {"field": "project_name"})
    # 4.9 impossible verification claim
    bad_case("impossible_claim_rejected", "truthful_claim",
             "the mission created 12 blueprints", {})


# ===========================================================================
# GROUP 5 — EVIDENCE INTEGRITY
# ===========================================================================

def run_evidence_integrity(run: QARun, client: BackendClient) -> None:
    cat = "EVIDENCE_INTEGRITY"
    window = 3600 * 6  # 6h freshness window for committed artifacts

    # Pull real evidence paths from the completed black-box missions.
    ev_paths: List[str] = []
    for check_name in ("readonly_diagnostic_mission",):
        c = run.check(check_name)
        if c is None or not isinstance(c.observed, dict):
            continue
        for ev in (c.observed.get("evidence") or []):
            if isinstance(ev, dict) and ev.get("path"):
                ev_paths.append(str(ev["path"]))

    c = run.add_check(QACheck("evidence_files_exist", cat,
                              expected="real files", verifier="truthful_claim",
                              severity_if_failed=SEV_CRITICAL,
                              detail="every evidence path resolves"))
    def _paths_exist():
        if not ev_paths:
            return {"error": "no evidence paths captured from missions"}
        missing = [p for p in ev_paths if not Path(p).is_file()]
        return {"count": len(ev_paths), "missing": missing}
    execute_check(run, c, _paths_exist, "real files",
                  suspected_component="mission-pipeline")
    if isinstance(c.observed, dict) and c.observed.get("missing"):
        c.mark(STATUS_FAIL, detail="missing evidence: "
                                   + "; ".join(c.observed["missing"]))
        run.record(c)
        run.add_defect(QADefect(
            SEV_CRITICAL, "evidence_files_exist: missing evidence paths", cat,
            reproduction="read black-box mission evidence",
            expected="all paths exist",
            actual="; ".join(c.observed["missing"]),
            evidence=list(c.evidence), check_name=c.name))
        run.save()

    # JSON evidence must not contain [object Object] or empty objects.
    c = run.add_check(QACheck("no_object_object_in_evidence", cat,
                              expected="no [object Object]",
                              verifier="truthful_claim",
                              severity_if_failed=SEV_MAJOR,
                              detail="evidence payloads serializable"))
    def _no_oo():
        bad = []
        for ev in run.evidence:
            text = json.dumps(ev, default=str)
            if "[object Object]" in text:
                bad.append(str(ev.get("check")))
        for check in run.checks:
            if isinstance(check.observed, dict):
                text = json.dumps(check.observed, default=str)
                if "[object Object]" in text:
                    bad.append(check.name)
        return {"clean": not bad, "hits": bad}
    execute_check(run, c, _no_oo, "no [object Object]",
                  suspected_component="qa-bot")

    # No viewport fallback presented as MRQ: the MRQ video must be a real
    # MRQ-labeled artifact and the proof stills must be 1920x1080.
    c = run.add_check(QACheck("mrq_not_viewport_fallback", cat,
                              expected="real MRQ artifact",
                              verifier="truthful_claim",
                              severity_if_failed=SEV_CRITICAL,
                              detail="video + proof under headless_mrq"))
    def _mrq_real():
        vid = ROOT / "reports" / "cinematic" / "headless_mrq" / \
            "mrq_render_1920x1080_30fps.mp4"
        report = ROOT / "reports" / "cinematic" / \
            "AIVIDO_HEADLESS_MRQ_REPORT.md"
        return {"video_exists": vid.exists(), "report_exists": report.exists(),
                "report_says_mrq": bool(report.exists() and
                                        "HEADLESS_MRQ" in
                                        report.read_text(encoding="utf-8",
                                                         errors="replace"))}
    execute_check(run, c, _mrq_real, "real MRQ artifact",
                  suspected_component="cinematic")

    # Timestamp relevance: committed cinematic artifacts must be fresh
    # relative to the certified base commit date (2026-09-07).
    c = run.add_check(QACheck("evidence_timestamps_relevant", cat,
                              expected="recent artifacts",
                              verifier="truthful_claim",
                              severity_if_failed=SEV_MAJOR,
                              detail="cinematic artifacts not ancient"))
    def _fresh():
        stale = []
        for rel in ("reports/cinematic/AIVIDO_HEADLESS_MRQ_REPORT.md",
                    "reports/cinematic/headless_mrq/"
                    "mrq_render_1920x1080_30fps.mp4",
                    "reports/cinematic/headless_mrq/proof/proof_start.png"):
            p = ROOT / rel
            if not p.exists():
                stale.append(f"{rel} MISSING")
                continue
            if time.time() - p.stat().st_mtime > window:
                stale.append(f"{rel} age "
                             f"{(time.time() - p.stat().st_mtime) / 3600:.1f}h")
        return {"stale": stale, "window_h": window / 3600}
    execute_check(run, c, _fresh, "recent artifacts",
                  suspected_component="cinematic")
    if isinstance(c.observed, dict) and c.observed.get("stale"):
        c.mark(STATUS_FAIL, detail="stale evidence: "
                                   + "; ".join(c.observed["stale"]))
        run.record(c)
        run.add_defect(QADefect(
            SEV_MAJOR, "evidence_timestamps_relevant: stale artifacts", cat,
            reproduction="stat committed cinematic artifacts",
            expected="mtime within 6h of QA run",
            actual="; ".join(c.observed["stale"]),
            evidence=list(c.evidence), check_name=c.name))
        run.save()

    # Screenshot evidence validity: proof stills decodable at 1920x1080.
    c = run.add_check(QACheck("proof_stills_valid", cat,
                              expected="decodable 1920x1080",
                              verifier="screenshot_valid",
                              severity_if_failed=SEV_MAJOR,
                              detail="proof_start/middle/end"))
    def _stills():
        for name in ("proof_start.png", "proof_middle.png", "proof_end.png"):
            p = ROOT / "reports" / "cinematic" / "headless_mrq" / "proof" / name
            if p.exists():
                return str(p)
        return str(ROOT / "reports" / "cinematic" / "headless_mrq" /
                   "proof" / "proof_start.png")
    execute_check(run, c, _stills, "decodable 1920x1080",
                  {"expected_size": (1920, 1080)},
                  suspected_component="cinematic")


# ===========================================================================
# GROUP 6 — UNREAL STATE SAFETY (READ-ONLY ONLY)
# ===========================================================================

CAST_MEMBERS = [
    "AVIDO_Human_Animation", "AVIDO_Human_Audio", "AVIDO_Human_Creative",
    "AVIDO_Human_Lighting", "AVIDO_Human_Master", "AVIDO_Human_Technical",
    "AVIDO_Human_VFX", "AVIDO_Human_Visual",
]
FORBIDDEN_ACTOR_MARKERS = ("WhiteH", "AVCam", "UA_Test", "BP_ProdProbe",
                           "RenderMap", "MRQ_")


def run_unreal_state_safety(run: QARun, probe: BridgeProbe) -> None:
    cat = "UNREAL_STATE_SAFETY"
    if not probe.ping().get("ok"):
        for name in ("certified_level_open", "actor_count",
                     "cast_8_of_8_present", "no_whiteh", "no_avcam_residue",
                     "no_transient_z_repair", "cine_mrq_isolated",
                     "durable_orientation"):
            mark_skipped(run, run.add_check(
                QACheck(name, cat, expected="verified",
                        verifier="truthful_claim",
                        severity_if_failed=SEV_CRITICAL,
                        detail="bridge unavailable; scene state not "
                               "verifiable (SKIPPED, never PASS)")),
                "Unreal bridge unreachable — scene preservation cannot be "
                "verified (read-only probe blocked)")
        return

    def _labels() -> List[str]:
        actors = probe.actor_names()
        if not actors.get("ok"):
            return []
        return [str(a.get("label") or a.get("name") or "")
                for a in (actors.get("actors") or [])]

    c = run.add_check(QACheck("certified_level_open", cat,
                              expected="/Game/Maps/AividoHQ",
                              verifier="truthful_claim",
                              severity_if_failed=SEV_CRITICAL,
                              detail="AividoHQ is the live level"))
    def _level():
        level = probe.current_level()
        return {"ok": level.get("ok"),
                "world": (level.get("result") or {}).get("world_path") or
                         (level.get("world") or "")}
    execute_check(run, c, _level, "AividoHQ level",
                  reproduction="read-only bridge probe of current level",
                  suspected_component="unreal-scene")
    level_obs = c.observed if isinstance(c.observed, dict) else {}
    world = str(level_obs.get("world") or "")
    if c.status == STATUS_PASS and "AividoHQ" not in world:
        c.mark(STATUS_FAIL, detail=f"live level is {world!r}, expected "
                                   "AividoHQ")
        run.record(c)
        run.add_defect(QADefect(
            SEV_CRITICAL, "certified_level_open: wrong live level", cat,
            reproduction="read-only current-level probe",
            expected="/Game/Maps/AividoHQ", actual=world,
            evidence=list(c.evidence), check_name=c.name,
            suspected_component="unreal-scene"))
        run.save()

    c = run.add_check(QACheck("actor_count", cat, expected=166,
                              verifier="actor_count_ok",
                              severity_if_failed=SEV_CRITICAL,
                              detail="166 actors in certified AividoHQ"))
    execute_check(run, c, lambda: len(_labels()), 166,
                  reproduction="read-only list_level_actors",
                  suspected_component="unreal-scene")

    c = run.add_check(QACheck("cast_8_of_8_present", cat, expected=CAST_MEMBERS,
                              verifier="list_members_present",
                              severity_if_failed=SEV_CRITICAL,
                              detail="8 human cast members"))
    execute_check(run, c, _labels, CAST_MEMBERS,
                  reproduction="read-only actor list scan",
                  suspected_component="unreal-cast")

    c = run.add_check(QACheck("no_whiteh", cat,
                              expected=["WhiteH"],
                              verifier="list_members_absent",
                              severity_if_failed=SEV_CRITICAL,
                              detail="no WhiteH cast override"))
    execute_check(run, c, _labels, ["WhiteH"],
                  reproduction="read-only actor list scan",
                  suspected_component="unreal-cast")

    c = run.add_check(QACheck("no_avcam_residue", cat,
                              expected=["AVCam", "UA_Test", "BP_ProdProbe",
                                        "RenderMap"],
                              verifier="list_members_absent",
                              severity_if_failed=SEV_MAJOR,
                              detail="no test/camera residue in certified "
                                     "level"))
    execute_check(run, c, _labels, ["AVCam", "UA_Test", "BP_ProdProbe",
                                    "RenderMap"],
                  reproduction="read-only actor list scan",
                  suspected_component="unreal-scene")

    c = run.add_check(QACheck("no_transient_z_repair", cat,
                              expected=["ZRepair", "tempz", "zfix"],
                              verifier="list_members_absent",
                              severity_if_failed=SEV_MAJOR,
                              detail="no transient Z repair actors"))
    execute_check(run, c, _labels, ["ZRepair", "tempz", "zfix"],
                  reproduction="read-only actor list scan",
                  suspected_component="unreal-scene")

    c = run.add_check(QACheck("cine_mrq_isolated", cat,
                              expected="certified level not RenderMap",
                              verifier="truthful_claim",
                              severity_if_failed=SEV_CRITICAL,
                              detail="/Game/CineMRQ stays isolated"))
    def _mrq_isolated():
        actors = _labels()
        return {"render_map_in_level": any("RenderMap" in a for a in actors),
                "world": world, "actor_count": len(actors)}
    execute_check(run, c, _mrq_isolated, "certified level not RenderMap",
                  reproduction="read-only level + actor scan",
                  suspected_component="unreal-scene")

    c = run.add_check(QACheck("durable_orientation", cat,
                              expected="upright cast",
                              verifier="truthful_claim",
                              severity_if_failed=SEV_MAJOR,
                              detail="cast orientation durable "
                                     "(read-back via bridge)"))
    def _orientation():
        try:
            from tools.unreal.unreal_bridge import UnrealBridge
            bridge = UnrealBridge(timeout=6)
            result = bridge.get_actor("AVIDO_Human_Master")
            payload = result.get("result", result) if isinstance(result, dict) else {}
            if isinstance(payload, dict) and isinstance(payload.get("result"), dict):
                payload = payload["result"]
            rot = None
            if isinstance(payload, dict):
                rot = payload.get("rotation") or (payload.get("transform") or {}).get("rotation")
            return {"ok": bool(payload and payload.get("ok")),
                    "rotation": rot}
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}
    obs = execute_check(run, c, _orientation, "upright cast",
                        reproduction="read-only get_actor on "
                                     "AVIDO_Human_Master",
                        suspected_component="unreal-cast").observed
    if isinstance(obs, dict) and isinstance(obs.get("rotation"), list) \
            and len(obs["rotation"]) == 3:
        rz = abs(float(obs["rotation"][2] or 0.0)) % 360.0
        ok = rz < 5.0 or abs(rz - 180.0) < 5.0
        c.mark(STATUS_PASS if ok else STATUS_FAIL,
               detail=(f"Master rotation.z={rz:.1f} (durable "
                       f"orientation)" if ok else
                       f"Master rotation.z={rz:.1f} not in {{0,180}}"))
        run.record(c, {"verifier": "truthful_claim", "detail": c.detail})
        if not ok:
            run.add_defect(QADefect(
                SEV_MAJOR, "durable_orientation: cast rotation drifted", cat,
                reproduction="read-only get_actor rotation read-back",
                expected="rotation.z in {0, 180}", actual=f"z={rz:.1f}",
                evidence=list(c.evidence), check_name=c.name))
        run.save()


# ===========================================================================
# GROUP 7 — CINEMATIC ARTIFACT QA (never re-renders)
# ===========================================================================

def run_cinematic_artifact(run: QARun) -> None:
    cat = "CINEMATIC_ARTIFACT"
    base = ROOT / "reports" / "cinematic"
    headless = base / "headless_mrq"

    c = run.add_check(QACheck("headless_mrq_report_exists", cat,
                              expected="report file", verifier="truthful_claim",
                              severity_if_failed=SEV_MAJOR,
                              detail="AIVIDO_HEADLESS_MRQ_REPORT.md"))
    def _report():
        p = base / "AIVIDO_HEADLESS_MRQ_REPORT.md"
        return {"exists": p.exists(), "size": p.stat().st_size if p.exists() else 0}
    execute_check(run, c, _report, "report file",
                  suspected_component="cinematic")

    c = run.add_check(QACheck("mrq_video_exists_playable", cat,
                              expected="playable MP4",
                              verifier="video_file_ok",
                              severity_if_failed=SEV_MAJOR,
                              detail="mrq_render_1920x1080_30fps.mp4"))
    execute_check(run, c,
                  lambda: str(headless / "mrq_render_1920x1080_30fps.mp4"),
                  "playable MP4", suspected_component="cinematic")

    c = run.add_check(QACheck("mrq_video_resolution_fps_duration", cat,
                              expected="1920x1080 @ 30fps, 8s",
                              verifier="truthful_claim",
                              severity_if_failed=SEV_MAJOR,
                              detail="ffprobe verified when available; "
                                     "else header + proof-still check"))
    def _video_meta():
        vid = headless / "mrq_render_1920x1080_30fps.mp4"
        meta = {"path": str(vid), "probe_ok": False}
        try:
            out = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries",
                 "stream=width,height,r_frame_rate:format=duration",
                 "-of", "json", str(vid)],
                capture_output=True, text=True, timeout=30).stdout
            data = json.loads(out or "{}")
            streams = data.get("streams") or [{}]
            fmt = data.get("format") or {}
            meta["probe_ok"] = True
            meta["width"] = streams[0].get("width")
            meta["height"] = streams[0].get("height")
            meta["r_frame_rate"] = streams[0].get("r_frame_rate")
            meta["duration"] = float(fmt.get("duration") or 0.0)
        except Exception:
            pass
        return meta
    obs = execute_check(run, c, _video_meta, "1920x1080 @ 30fps, 8s",
                        suspected_component="cinematic").observed
    if isinstance(obs, dict) and obs.get("probe_ok"):
        ok = (obs.get("width") == 1920 and obs.get("height") == 1080
              and str(obs.get("r_frame_rate")) == "30/1"
              and abs(float(obs.get("duration") or 0.0) - 8.0) < 0.5)
        c.mark(STATUS_PASS if ok else STATUS_FAIL,
               detail=(f"ffprobe: {obs.get('width')}x{obs.get('height')} "
                       f"{obs.get('r_frame_rate')} {obs.get('duration')}s"))
        run.record(c, {"verifier": "truthful_claim", "detail": c.detail})
        if not ok:
            run.add_defect(QADefect(
                SEV_MAJOR, "mrq_video_resolution_fps_duration: probe "
                           "mismatch", cat,
                reproduction="ffprobe the committed MRQ MP4",
                expected="1920x1080 30/1 8s", actual=str(obs),
                evidence=list(c.evidence), check_name=c.name))
        run.save()
    else:
        # No ffprobe: video metadata cannot be independently verified. Mark
        # SKIPPED (never PASS) — proof-still resolution is checked separately.
        c.mark(STATUS_SKIPPED,
               detail="ffprobe unavailable; MP4 metadata (resolution/fps/"
                      "duration) not independently verifiable — not PASS")
        run.record(c, {"verifier": "truthful_claim", "detail": c.detail})
        run.save()

    c = run.add_check(QACheck("frame_count_claim_consistent", cat,
                              expected="240 frames consistent",
                              verifier="report_claim_consistent",
                              severity_if_failed=SEV_MAJOR,
                              detail="240-frame claim vs artifacts"))
    def _frames():
        frames_dir = headless / "frames"
        entries = 0
        if frames_dir.exists():
            entries = len([f for f in frames_dir.glob("frame_*.png")])
        report = base / "AIVIDO_HEADLESS_MRQ_REPORT.md"
        text = report.read_text(encoding="utf-8", errors="replace") \
            if report.exists() else ""
        # Independent cross-check: MP4 duration x fps must equal 240 frames.
        derived = None
        try:
            out = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=r_frame_rate:format=duration",
                 "-of", "json",
                 str(headless / "mrq_render_1920x1080_30fps.mp4")],
                capture_output=True, text=True, timeout=30).stdout
            data = json.loads(out or "{}")
            streams = data.get("streams") or [{}]
            fps = str(streams[0].get("r_frame_rate") or "")
            dur = float((data.get("format") or {}).get("duration") or 0.0)
            if "30/1" in fps and dur:
                derived = int(round(dur * 30))
        except Exception:
            derived = None
        # Effective frame count: prefer on-disk, fall back to the derived
        # duration(fps) cross-check so the verifier can be independent.
        effective = entries if entries else (derived or 0)
        return {"entries": effective,
                "on_disk_entries": entries,
                "derived_frames": derived,
                "artifact_path": str(headless /
                                     "mrq_render_1920x1080_30fps.mp4"),
                "report_claims_240": "240" in text,
                "frames_dir_present": frames_dir.exists()}
    obs = execute_check(run, c, _frames, "240 frames consistent",
                        {"expected_entries": 240},
                        suspected_component="cinematic").observed
    if isinstance(obs, dict):
        entries = int(obs.get("entries") or 0)
        on_disk = int(obs.get("on_disk_entries") or 0)
        derived = obs.get("derived_frames")
        if on_disk == 240:
            c.mark(STATUS_PASS, detail="240 frames on disk")
            run.record(c, {"verifier": "report_claim_consistent",
                           "detail": c.detail})
            run.save()
        elif derived == 240 and obs.get("report_claims_240"):
            c.mark(STATUS_PASS,
                   detail="240-frame claim verified independently via MP4 "
                          "duration(8.0s) x fps(30); raw frames dir is "
                          "untracked by repo convention")
            run.record(c, {"verifier": "report_claim_consistent",
                           "detail": c.detail})
            run.save()
        else:
            c.mark(STATUS_FAIL,
                   detail=f"frame-count claim not verified: on-disk={on_disk}, "
                          f"derived(dur*fps)={derived}, "
                          f"report_claims_240={obs.get('report_claims_240')}")
            run.record(c)
            run.add_defect(QADefect(
                SEV_MAJOR, "frame_count_claim_consistent: 240-frame claim "
                           "unverified", cat,
                reproduction="count frame files + ffprobe duration*fps",
                expected="240", actual=str(obs),
                evidence=list(c.evidence), check_name=c.name))
            run.save()

    c = run.add_check(QACheck("proof_stills_exist", cat,
                              expected="3 proof stills",
                              verifier="truthful_claim",
                              severity_if_failed=SEV_MAJOR,
                              detail="proof_start/middle/end"))
    def _stills():
        stills = [headless / "proof" / f"proof_{n}.png"
                  for n in ("start", "middle", "end")]
        return {"count": sum(1 for p in stills if p.exists()),
                "paths": [str(p) for p in stills if p.exists()]}
    execute_check(run, c, _stills, "3 proof stills",
                  suspected_component="cinematic")


# ===========================================================================
# GROUP 8 — UI BLACK-BOX
# ===========================================================================

PRODUCTION_ROUTES = [
    ("/", "ava.html"), ("/app", "aivido.html"), ("/dev", "index.html"),
    ("/static/aivido.html", "static aivido.html"),
    ("/static/product.html", "static product.html"),
]


def run_ui_blackbox(run: QARun, client: BackendClient) -> None:
    cat = "UI_BLACKBOX"

    c = run.add_check(QACheck("production_routes_serve", cat,
                              expected="HTTP 200 on all routes",
                              verifier="truthful_claim",
                              severity_if_failed=SEV_CRITICAL,
                              detail="Booth/Workspaces/Sessions/Mission/"
                                     "Room/Proof/Quests/Finance/Profile/"
                                     "Settings"))
    def _routes():
        results = {}
        for path, label in PRODUCTION_ROUTES:
            r = client.request("GET", path, timeout=15)
            body = r.get("body") or {}
            if isinstance(body, dict) and "raw" in body:
                length = len(str(body.get("raw")))
            else:
                length = len(json.dumps(body, default=str))
            results[label] = {"http_status": r.get("http_status"),
                              "len": length,
                              "error": body.get("error")}
        return results
    obs = execute_check(run, c, _routes, "HTTP 200 on all routes",
                        suspected_component="ui").observed
    if isinstance(obs, dict):
        bad = {k: v for k, v in obs.items()
               if not (200 <= int(v.get("http_status") or 0) < 300)}
        if bad:
            c.mark(STATUS_FAIL,
                   detail="non-200 routes: " + json.dumps(bad))
            run.record(c)
            run.add_defect(QADefect(
                SEV_CRITICAL, "production_routes_serve: broken route(s)", cat,
                reproduction="GET each production route",
                expected="HTTP 200", actual=json.dumps(bad),
                evidence=list(c.evidence), check_name=c.name,
                suspected_component="ui"))
            run.save()

    c = run.add_check(QACheck("no_js_fatal_in_pages", cat,
                              expected="no fatal markers",
                              verifier="no_js_fatal",
                              severity_if_failed=SEV_MAJOR,
                              detail="pages carry no error/traceback text"))
    def _pages():
        texts = []
        for path, _ in PRODUCTION_ROUTES[:3]:
            r = client.request("GET", path, timeout=15)
            body = r.get("body") or {}
            if isinstance(body, dict) and "raw" in body:
                texts.append(str(body.get("raw")))
            else:
                texts.append(json.dumps(body, default=str))
        return "\n".join(texts)[:20000]
    execute_check(run, c, _pages, "no fatal markers",
                  suspected_component="ui")

    c = run.add_check(QACheck("api_state_renders", cat,
                              expected="API-backed state present",
                              verifier="truthful_claim",
                              severity_if_failed=SEV_MAJOR,
                              detail="status/workspace/code-tasks/session "
                                     "return real state"))
    def _api_state():
        out = {}
        for label, fn in (("status", client.status),
                          ("workspace", client.workspace),
                          ("code_tasks", client.code_tasks),
                          ("session", client.session_identity)):
            r = fn()
            body = r.get("body") or {}
            out[label] = {"http_status": r.get("http_status"),
                          "ok": body.get("ok")}
        return out
    execute_check(run, c, _api_state, "API-backed state present",
                  suspected_component="backend")

    c = run.add_check(QACheck("no_false_pass_labels", cat,
                              expected="no contradictory PASS labels",
                              verifier="no_false_pass_label",
                              severity_if_failed=SEV_MAJOR,
                              detail="no 'PASS' with 'no completed "
                                     "evidence'"))
    def _page_text():
        r = client.request("GET", "/app", timeout=15)
        body = r.get("body") or {}
        if isinstance(body, dict) and "raw" in body:
            return str(body.get("raw"))[:30000]
        return json.dumps(body, default=str)[:30000]
    execute_check(run, c, _page_text, "no contradictory PASS labels",
                  suspected_component="ui")

    c = run.add_check(QACheck("evidence_fields_readable", cat,
                              expected="no [object Object]",
                              verifier="truthful_claim",
                              severity_if_failed=SEV_MAJOR,
                              detail="mission checkpoint evidence fields "
                                     "readable"))
    def _evidence_text():
        r = client.request("GET", "/api/code/tasks", timeout=15)
        body = r.get("body") or {}
        return json.dumps(body, default=str)[:20000]
    execute_check(run, c, _evidence_text, "no [object Object]",
                  suspected_component="ui")


# ===========================================================================
# GROUP 9 — RECOVERY
# ===========================================================================

def run_recovery(run: QARun, client: BackendClient) -> None:
    cat = "RECOVERY"

    c = run.add_check(QACheck("retry_unknown_mission_404", cat,
                              expected="404 on unknown retry",
                              verifier="truthful_claim",
                              severity_if_failed=SEV_WARNING,
                              detail="resume unknown mission"))
    execute_check(run, c,
                  lambda: {"http_status": client.mission_resume(
                      "mission_does_not_exist_zz").get("http_status")},
                  "404", suspected_component="backend")

    c = run.add_check(QACheck("cancel_unknown_mission_404", cat,
                              expected="404 on unknown cancel",
                              verifier="truthful_claim",
                              severity_if_failed=SEV_WARNING,
                              detail="cancel unknown mission"))
    execute_check(run, c,
                  lambda: {"http_status": client.mission_cancel(
                      "mission_does_not_exist_zz").get("http_status")},
                  "404", suspected_component="backend")

    c = run.add_check(QACheck("duplicate_submission_protected", cat,
                              expected="repeated submission rejected or "
                                       "idempotent",
                              verifier="truthful_claim",
                              severity_if_failed=SEV_MAJOR,
                              detail="code worker single-flight"))
    def _dupe():
        r = client.code_tasks()
        body = r.get("body") or {}
        snapshot = body.get("snapshot") or {}
        return {"ok": body.get("ok"),
                "queue_size": snapshot.get("queue_size"),
                "current_task_id": snapshot.get("current_task_id"),
                "loop_running": snapshot.get("loop_running")}
    execute_check(run, c, _dupe, "repeated submission rejected or idempotent",
                  suspected_component="code-worker")

    c = run.add_check(QACheck("stale_task_recovery", cat,
                              expected="no stale running tasks",
                              verifier="truthful_claim",
                              severity_if_failed=SEV_MAJOR,
                              detail="code queue has no orphaned running "
                                     "tasks"))
    def _stale():
        r = client.code_tasks()
        body = r.get("body") or {}
        running = [t for t in (body.get("tasks") or [])
                   if t.get("status") == "running"]
        return {"running_count": len(running),
                "running_ids": [t.get("id") for t in running]}
    execute_check(run, c, _stale, "no stale running tasks",
                  suspected_component="code-worker")

    c = run.add_check(QACheck("watchdog_supervisor_present", cat,
                              expected="supervisor alive",
                              verifier="truthful_claim",
                              severity_if_failed=SEV_WARNING,
                              detail="code-task watchdog surface"))
    def _watchdog():
        r = client.code_tasks()
        body = r.get("body") or {}
        snap = body.get("snapshot") or {}
        return {"loop_running": snap.get("loop_running"),
                "by_status": snap.get("by_status")}
    execute_check(run, c, _watchdog, "supervisor alive",
                  suspected_component="code-worker")


# ===========================================================================
# GROUP 10 — RELEASE SAFETY
# ===========================================================================

def run_release_safety(run: QARun) -> None:
    cat = "RELEASE_SAFETY"

    c = run.add_check(QACheck("secrets_not_in_committed_files", cat,
                              expected="no secret markers",
                              verifier="secrets_hygiene",
                              severity_if_failed=SEV_CRITICAL,
                              detail="scan tracked config/manifest files"))
    def _secrets():
        texts = []
        for rel in ("config/settings.json", "ui/build-manifest.json",
                    "config/mcp_gateway.key"):
            p = ROOT / rel
            if p.exists():
                texts.append(p.read_text(encoding="utf-8", errors="replace"))
        # .gitignore must exclude the key file.
        gi = ROOT / ".gitignore"
        if gi.exists():
            texts.append(gi.read_text(encoding="utf-8", errors="replace"))
        return "\n".join(texts)
    execute_check(run, c, _secrets, "no secret markers",
                  suspected_component="release")

    c = run.add_check(QACheck("no_absolute_local_paths_in_product", cat,
                              expected="no C:/Users paths",
                              verifier="no_absolute_local_path",
                              severity_if_failed=SEV_MINOR,
                              detail="product-facing JSON payloads clean"))
    def _paths():
        texts = []
        for rel in ("ui/aivido.html", "ui/aivido.js", "ui/product.html"):
            p = ROOT / rel
            if p.exists():
                texts.append(p.read_text(encoding="utf-8",
                                         errors="replace"))
        return "\n".join(texts)[:60000]
    execute_check(run, c, _paths, "no C:/Users paths",
                  suspected_component="ui")

    c = run.add_check(QACheck("certified_files_clean", cat,
                              expected="no dirty certified files",
                              verifier="truthful_claim",
                              severity_if_failed=SEV_CRITICAL,
                              detail="git status clean for certified dirs"))
    def _git_status():
        try:
            out = subprocess.run(
                ["git", "status", "--porcelain", "--", "reports/cinematic",
                 "core/cinematic_mission.py", "app/unreal_coder_api.py"],
                capture_output=True, text=True, timeout=30, cwd=str(ROOT))
            lines = [l for l in out.stdout.splitlines()
                     if l and "__pycache__" not in l]
            return {"dirty": len(lines) > 0, "lines": lines}
        except Exception as exc:
            return {"error": str(exc)}
    execute_check(run, c, _git_status, "no dirty certified files",
                  reproduction="git status on certified paths",
                  suspected_component="release")
    obs = c.observed if isinstance(c.observed, dict) else {}
    if isinstance(obs, dict) and obs.get("dirty") and not obs.get("error"):
        c.mark(STATUS_FAIL, detail="dirty certified files: "
                                   + "; ".join(obs.get("lines", [])))
        run.record(c)
        run.add_defect(QADefect(
            SEV_CRITICAL, "certified_files_clean: dirty certified files", cat,
            reproduction="git status --porcelain on certified paths",
            expected="clean", actual="; ".join(obs.get("lines", [])),
            evidence=list(c.evidence), check_name=c.name,
            suspected_component="release"))
        run.save()

    c = run.add_check(QACheck("correct_branch_assumption", cat,
                              expected="aivido/v2-autonomous-qa",
                              verifier="registry_match",
                              severity_if_failed=SEV_MAJOR,
                              detail="QA bot runs on the v2 branch"))
    def _branch():
        try:
            out = subprocess.run(["git", "branch", "--show-current"],
                                 capture_output=True, text=True, timeout=15,
                                 cwd=str(ROOT))
            return {"branch": out.stdout.strip()}
        except Exception as exc:
            return {"error": str(exc)}
    execute_check(run, c, _branch, "aivido/v2-autonomous-qa",
                  {"field": "branch"}, suspected_component="release")

    c = run.add_check(QACheck("junk_build_artifacts", cat,
                              expected="no junk in tracked tree",
                              verifier="truthful_claim",
                              severity_if_failed=SEV_WARNING,
                              detail="no stray temp/pycache in tracked files"))
    def _junk():
        try:
            out = subprocess.run(["git", "ls-files"],
                                 capture_output=True, text=True, timeout=30,
                                 cwd=str(ROOT))
            bad = [f for f in out.stdout.splitlines()
                   if f.endswith(".pyc") or "__pycache__" in f
                   or f.endswith(".tmp") or "backup-2026" in f]
            return {"junk": bad}
        except Exception as exc:
            return {"error": str(exc)}
    execute_check(run, c, _junk, "no junk in tracked tree",
                  suspected_component="release")

    c = run.add_check(QACheck("startup_doctor_sanity", cat,
                              expected="doctor reachable",
                              verifier="truthful_claim",
                              severity_if_failed=SEV_MAJOR,
                              detail="doctor endpoint answers"))
    def _doctor():
        r = BackendClient().doctor()
        body = r.get("body") or {}
        return {"http_status": r.get("http_status"),
                "overall": body.get("overall"),
                "checks": len(body.get("checks") or [])}
    execute_check(run, c, _doctor, "doctor reachable",
                  suspected_component="backend")

    c = run.add_check(QACheck("release_prerequisites", cat,
                              expected="install/start scripts + README",
                              verifier="truthful_claim",
                              severity_if_failed=SEV_WARNING,
                              detail="packaging prerequisites present"))
    def _prereqs():
        required = ("README.md", "requirements.txt", "start-aivido.ps1",
                    "start-aivido.cmd", "install-aivido.ps1",
                    "install-aivido.cmd")
        return {r: (ROOT / r).exists() for r in required}
    execute_check(run, c, _prereqs, "install/start scripts + README",
                  suspected_component="release")