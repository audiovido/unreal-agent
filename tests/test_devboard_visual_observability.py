from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app import api


FINAL_PROOF = Path("assetlib/proof/vehicle_showcase_controlled_20260905/final_fresh_vehicle.png")


def _snapshot(final_proof: Path = FINAL_PROOF):
    return {
        "id": "task-ui-observability",
        "task": "vehicle showcase",
        "state": "COMPLETE",
        "final_verdict": "PASS",
        "completion_message": "Execution complete.",
        "visual_profile": "vehicle_showcase",
        "visual_score_measured": 9.19,
        "visual_floor": 8.5,
        "visual_self_fix": {
            "status": "COMPLETE",
            "fresh_hash_changed": True,
            "passes": [
                {
                    "index": 1,
                    "hash": "pass-hash-1",
                    "strategy": "exposure_reduce_highlights",
                    "kept": True,
                    "reverted": False,
                    "score": {"overall": 8.83},
                    "defects": [],
                }
            ],
            "final": {
                "metrics": {
                    "subject_bbox": [558, 73, 1515, 697],
                    "subject_coverage": 0.4075,
                }
            },
        },
        "visual_proof": [
            {"role": "initial", "path": "before.png", "sha256": "before-hash"},
            {"role": "final", "path": str(final_proof), "sha256": "final-hash"},
        ],
    }


def test_execution_detail_reuses_canonical_visual_evidence(monkeypatch, tmp_path):
    proof = tmp_path / "assetlib" / "proof" / "vehicle_showcase" / "final.png"
    proof.parent.mkdir(parents=True)
    proof.write_bytes(b"hermetic-proof")
    monkeypatch.setattr(api, "ROOT", tmp_path)
    monkeypatch.setattr(api, "last_execution_snapshot", api._execution_detail(_snapshot(proof)))

    with TestClient(api.app, raise_server_exceptions=False) as client:
        response = client.get("/api/execution/task-ui-observability")

    assert response.status_code == 200
    visual = response.json()["execution"]["visual"]
    assert visual["profile"] == "vehicle_showcase"
    assert visual["score"] == 9.19
    assert visual["required_floor"] == 8.5
    assert visual["acceptance_verdict"] == "PASS"
    assert visual["subject_bbox"] == [558, 73, 1515, 697]
    assert visual["subject_coverage"] == 0.4075
    assert visual["issues"] == []
    assert visual["proof"]["fresh"] is True
    assert visual["proof"]["previous"]["sha256"] == "before-hash"
    assert visual["proof"]["final"]["sha256"] == "final-hash"
    assert visual["passes"][0] == {
        "index": 1,
        "score": 8.83,
        "strategy": "exposure_reduce_highlights",
        "kept": True,
        "reverted": False,
        "proof_hash": "pass-hash-1",
    }
    assert visual["terminal_state"] == "COMPLETE"
    assert visual["proof_preview_url"].endswith("/proof/final")

    with TestClient(api.app, raise_server_exceptions=False) as client:
        proof_response = client.get("/api/execution/task-ui-observability/proof/final")
    assert proof_response.status_code == 200
    assert proof_response.headers["content-type"].startswith("image/png")


def test_execution_detail_leaves_unavailable_values_unevaluated(monkeypatch):
    monkeypatch.setattr(
        api,
        "last_execution_snapshot",
        api._execution_detail({"id": "task-empty", "state": "RUNNING"}),
    )

    with TestClient(api.app, raise_server_exceptions=False) as client:
        response = client.get("/api/execution/task-empty")

    assert response.status_code == 200
    visual = response.json()["execution"]["visual"]
    assert visual["profile"] is None
    assert visual["score"] is None
    assert visual["acceptance_verdict"] is None
    assert visual["proof"]["fresh"] is None
    assert visual["passes"] == []
    assert visual["terminal_state"] is None


def test_devboard_contains_canonical_visual_inspector_bindings():
    source = Path("ui/devboard.html").read_text(encoding="utf-8")

    for field in (
        "visualProfile",
        "visualScore",
        "visualFloor",
        "visualVerdict",
        "visualBbox",
        "visualCoverage",
        "visualIssues",
        "visualEnvironment",
        "visualFreshness",
        "visualProofHashes",
        "visualProofPath",
        "visualPasses",
        "visualTerminal",
        "/api/execution/",
    ):
        assert field in source
    assert "Not evaluated" in source
