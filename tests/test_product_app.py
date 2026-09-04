"""Hermetic tests for the product server (app/product_app.py).

The FastAPI app is imported normally; every endpoint that would touch a
live editor is short-circuited by patching the product session, so no
bridge/editor is needed.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.product_app import app
from app.product_app import product_session


def _client():
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Static surface
# ---------------------------------------------------------------------------

def test_product_page_served():
    with _client() as c:
        r = c.get("/")
        assert r.status_code == 200
        assert "Unreal Agent" in r.text
        assert "product.js" in r.text


def test_static_assets_served():
    with _client() as c:
        for path in ("/static/product.js", "/static/product.css"):
            r = c.get(path)
            assert r.status_code == 200
            assert len(r.content) > 500


def test_status_contract():
    with _client() as c:
        r = c.get("/api/ua/status")
        assert r.status_code == 200
        d = r.json()
        for key in ("state", "project", "status_text", "current_stage",
                    "elapsed_s", "progress", "final", "proof", "stages",
                    "timings", "error_detail"):
            assert key in d, key


# ---------------------------------------------------------------------------
# Task lifecycle guards (no editor needed)
# ---------------------------------------------------------------------------

def test_run_empty_prompt_rejected():
    with _client() as c:
        r = c.post("/api/ua/run", json={"prompt": "   "})
        assert r.status_code == 400


def test_run_requires_connection(monkeypatch):
    monkeypatch.setattr(product_session, "_bridge_ok", lambda: False)
    monkeypatch.setattr(product_session, "_bridge_identity", lambda: {})
    with _client() as c:
        r = c.post("/api/ua/run", json={"prompt": "Add a cube"})
        assert r.status_code == 409
        assert "Not connected" in str(r.json().get("detail", ""))


def test_run_missing_bridge_state(monkeypatch):
    monkeypatch.setattr(product_session, "_bridge_ok", lambda: False)
    with _client() as c:
        r = c.post("/api/ua/run", json={"prompt": "remove the prop"})
        assert r.status_code == 409


def test_cancel_is_idempotent():
    with _client() as c:
        r = c.post("/api/ua/cancel")
        assert r.status_code == 200
        assert r.json()["ok"] is True


# ---------------------------------------------------------------------------
# Proof serving is traversal-safe
# ---------------------------------------------------------------------------

def test_proof_file_traversal_blocked():
    with _client() as c:
        r = c.get("/api/ua/proof-file",
                  params={"path": str(
                      __import__("pathlib").Path(
                          "config/product.json").resolve())})
        assert r.status_code == 404


def test_proof_file_missing_404():
    with _client() as c:
        r = c.get("/api/ua/proof-file",
                  params={"path": "C:/definitely/not/there.png"})
        assert r.status_code == 404


def test_evidence_listing_shape():
    with _client() as c:
        r = c.get("/api/ua/evidence")
        assert r.status_code == 200
        d = r.json()
        assert "evidence" in d
        for item in d["evidence"]:
            assert item["url"].startswith("/api/ua/proof/")


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

def test_projects_returns_known_list():
    with _client() as c:
        r = c.get("/api/ua/projects")
        assert r.status_code == 200
        d = r.json()
        assert "known" in d and "last" in d
