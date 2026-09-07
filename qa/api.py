"""qa/api.py — minimal QA bot API.

    POST /api/qa/run                 start a durable autonomous QA run
    GET  /api/qa/runs                list runs
    GET  /api/qa/runs/{id}           run detail (checks/defects/verdict)
    GET  /api/qa/runs/{id}/report    generated report (md/json)
    GET  /api/qa/runs/{id}/defects   defect list
    GET  /api/qa/defects             durable ledger

Runs are durable under memory/qa/runs/{id}/ and recoverable (interrupted
runs are marked BLOCKED on load, never force-PASSed).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from qa import runner
from qa.ledger import LEDGER_PATH, load_ledger, open_defect_summary
from qa.model import (
    DEFAULT_RUNS_DIR, QARun, new_run_id,
    STATUS_RUNNING,
)

router = APIRouter(prefix="/api/qa")


class RunRequest(BaseModel):
    target: str = "Aivido V2 runtime"


@router.post("/run")
def qa_run(body: Optional[RunRequest] = None) -> Dict[str, Any]:
    body = body or RunRequest()
    run = runner.start_run(body.target or "Aivido V2 runtime")
    return {"ok": True, "run_id": run.id, "status": run.status,
            "message": "QA run started; poll GET /api/qa/runs/{id}"}


@router.get("/runs")
def qa_runs() -> Dict[str, Any]:
    ids = QARun.list_ids()
    runs = []
    for run_id in ids:
        run = QARun.load(run_id)
        if run is None:
            continue
        runs.append({
            "id": run.id, "status": run.status, "verdict": run.verdict,
            "started_at": run.started_at, "finished_at": run.finished_at,
            "summary": run.summary(),
            "running": runner.is_running(run.id),
        })
    return {"ok": True, "runs": runs}


@router.get("/runs/{run_id}")
def qa_run_detail(run_id: str) -> Dict[str, Any]:
    run = QARun.load(run_id)
    if run is None:
        raise HTTPException(404, f"unknown QA run {run_id}")
    data = run.to_dict()
    data["running"] = runner.is_running(run_id)
    return {"ok": True, "run": data}


@router.get("/runs/{run_id}/report")
def qa_run_report(run_id: str, fmt: str = "json") -> Any:
    run = QARun.load(run_id)
    if run is None:
        raise HTTPException(404, f"unknown QA run {run_id}")
    from qa.verdict import REPORT_JSON, REPORT_MD
    path = REPORT_JSON if fmt == "json" else REPORT_MD
    if not path.exists():
        raise HTTPException(409, "report not generated yet")
    if fmt == "md":
        return FileResponse(str(path), media_type="text/markdown")
    import json
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/runs/{run_id}/defects")
def qa_run_defects(run_id: str) -> Dict[str, Any]:
    run = QARun.load(run_id)
    if run is None:
        raise HTTPException(404, f"unknown QA run {run_id}")
    return {"ok": True, "defects": [d.to_dict() for d in run.defects],
            "counts": run.defects_by_severity()}


@router.get("/defects")
def qa_defects() -> Dict[str, Any]:
    return {"ok": True, **load_ledger(), "open_summary": open_defect_summary()}


def register_qa_api(app) -> None:
    """Recover interrupted runs and mount the QA router."""
    QARun.recover_interrupted()
    app.include_router(router)