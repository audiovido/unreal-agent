"""qa/ledger.py — durable machine-readable defect ledger.

Single source of truth: reports/qa/AIVIDO_V2_QA_DEFECTS.json. Defects are
merged from QA runs (deduped by id) and carry an explicit status
(OPEN/FIXED/VERIFIED/WONT_FIX/BLOCKED). Failures are never hidden to force
a release PASS.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from qa.model import (
    LEDGER_OPEN, LEDGER_FIXED, LEDGER_VERIFIED, LEDGER_WONT_FIX,
    LEDGER_BLOCKED, QADefect, REPORTS_DIR, STATUS_PASS,
)

LEDGER_PATH = REPORTS_DIR / "AIVIDO_V2_QA_DEFECTS.json"


def _default() -> Dict[str, Any]:
    return {
        "schema": "aivido.v2.qa-defects.v1",
        "generated_at": time.time(),
        "defects": [],
        "counts": {},
    }


def load_ledger() -> Dict[str, Any]:
    if not LEDGER_PATH.exists():
        return _default()
    try:
        data = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("defects"), list):
            return data
    except Exception:
        pass
    return _default()


def _recount(data: Dict[str, Any]) -> None:
    counts: Dict[str, int] = {}
    for d in data.get("defects", []):
        counts[d.get("status", LEDGER_OPEN)] = \
            counts.get(d.get("status", LEDGER_OPEN), 0) + 1
    data["counts"] = counts
    data["generated_at"] = time.time()


def save_ledger(data: Dict[str, Any]) -> Path:
    _recount(data)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = LEDGER_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(LEDGER_PATH)
    return LEDGER_PATH


def merge_run_defects(defects: List[QADefect], *, status: str = LEDGER_OPEN,
                      run_id: str = "") -> Dict[str, Any]:
    """Merge defects from one run into the durable ledger (dedupe by id)."""
    data = load_ledger()
    existing = {d.get("id"): d for d in data.get("defects", [])}
    for defect in defects:
        d = defect.to_dict()
        d["status"] = status
        d["run_id"] = run_id
        existing[d["id"]] = d
    data["defects"] = list(existing.values())
    save_ledger(data)
    return data


def reconcile_ledger(*, run_id: str = "", checks=None,
                     current_run_defects: Optional[List[Any]] = None,
                     verified_status: str = LEDGER_VERIFIED) -> Dict[str, Any]:
    """Reconcile the durable ledger against the results of the most recent
    run so prior OPEN defects are not left stale forever.

    Any OPEN/BLOCKED defect whose check now PASSES in `checks` is marked
    VERIFIED (the run is independent evidence the defect no longer
    reproduces). Defects whose check still FAILs stay OPEN; defects with no
    matching check in this run are left untouched (we have no new evidence
    either way). When the same check reproduces a fresh defect in the
    current run, older OPEN ledger entries for that check are marked
    VERIFIED so the ledger keeps exactly one OPEN entry per live defect
    (history is retained, never deleted). Failures are never hidden to
    force a release PASS.
    """
    data = load_ledger()
    status_by_check = {
        c.name: c.status for c in (checks or []) if c is not None
    }
    reproduced = {
        getattr(d, "check_name", "") for d in (current_run_defects or [])
    }
    current_ids = {
        getattr(d, "id", "") for d in (current_run_defects or [])
    }
    changed = 0
    for d in data.get("defects", []):
        if d.get("status") not in (LEDGER_OPEN, LEDGER_BLOCKED):
            continue
        cn = d.get("check_name")
        if not cn or cn not in status_by_check:
            continue
        if status_by_check[cn] == STATUS_PASS:
            d["status"] = verified_status
            if run_id:
                d["verified_in_run"] = run_id
            changed += 1
        elif cn in reproduced and d.get("id") not in current_ids:
            # A fresh OPEN entry for the same defect exists in this run;
            # retire this older duplicate entry (never the run's own).
            d["status"] = verified_status
            d["superseded_in_run"] = run_id or d.get("run_id", "")
            changed += 1
    if changed:
        save_ledger(data)
    return data


def open_defect_summary() -> Dict[str, Any]:
    """Counts of currently-OPEN ledger defects by severity (for the UI/API)."""
    data = load_ledger()
    open_d = [d for d in data.get("defects", [])
              if d.get("status") in (LEDGER_OPEN, LEDGER_BLOCKED)]
    return {
        "open": len(open_d),
        "by_severity": counts_by_severity(open_d),
        "defects": open_d,
    }


def set_defect_status(defect_id: str, status: str) -> bool:
    """Open/close a defect's ledger status explicitly."""
    data = load_ledger()
    for d in data.get("defects", []):
        if d.get("id") == defect_id:
            d["status"] = status
            save_ledger(data)
            return True
    return False


def open_defects() -> List[Dict[str, Any]]:
    data = load_ledger()
    return [d for d in data.get("defects", [])
            if d.get("status") in (LEDGER_OPEN, LEDGER_BLOCKED)]


def counts_by_severity(defects: List[Dict[str, Any]]) -> Dict[str, int]:
    from qa.model import SEVERITIES
    out = {s: 0 for s in SEVERITIES}
    for d in defects:
        out[d.get("severity", "WARNING")] = \
            out.get(d.get("severity", "WARNING"), 0) + 1
    return out