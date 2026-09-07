"""Hermetic tests for the QA API endpoints (qa/api.py router)."""
from __future__ import annotations

import threading

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import qa.api as qa_api
import qa.model as model
import qa.runner as runner


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(model, "DEFAULT_RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(runner, "_RUN_THREADS", {})
    app = FastAPI()
    from qa.api import router
    app.include_router(router)
    return TestClient(app)


def test_runs_list_and_detail(client):
    r = client.get("/api/qa/runs")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    r2 = client.get("/api/qa/runs/missing")
    assert r2.status_code == 404


def test_unknown_run_defects_404(client):
    r = client.get("/api/qa/runs/missing/defects")
    assert r.status_code == 404


def test_defects_ledger_endpoint(client):
    r = client.get("/api/qa/defects")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert isinstance(r.json().get("defects"), list)


def test_report_endpoint_404_before_generation(client):
    r = client.get("/api/qa/runs/x/report")
    assert r.status_code == 404


def test_post_run_starts_background(client, monkeypatch, tmp_path):
    """POST /api/qa/run creates a durable run (running flag) without
    touching the live backend (runner executes against a stub backend)."""
    import qa.checks as checks_mod
    started = []

    class _FakeBackend:
        pass

    def fake_execute(run_id):
        run = model.QARun.load(run_id)
        run.status = "COMPLETED"
        run.finished_at = 1.0
        run.score = 100.0
        run.save()
        return run.to_dict()

    monkeypatch.setattr(runner, "execute_run", fake_execute)
    r = client.post("/api/qa/run", json={"target": "hermetic"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    run_id = body["run_id"]
    assert run_id
    detail = client.get(f"/api/qa/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["run"]["target"] == "hermetic"