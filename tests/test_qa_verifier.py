"""Hermetic tests for the independent verifier registry (qa/verifier.py).

Every PASS must carry independent evidence; these tests prove the
verifiers reject fabricated results.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from qa.model import QACheck
from qa.verifier import (
    VERIFIERS, run_verifier, verify,
)


def test_verifier_registry_populated():
    for name in ("mission_verdict", "screenshot_valid", "truthful_claim",
                 "evidence_file_ok", "expect_failure", "no_stale_duplicate",
                 "video_file_ok", "actor_count_ok", "health_ok"):
        assert name in VERIFIERS


def test_unknown_verifier_cannot_pass():
    check = QACheck("x", "G", verifier="does_not_exist")
    result = verify(check, "expected", {"ok": True})
    assert result["ok"] is False


def test_mission_verdict_requires_complete_pass_evidence(tmp_path):
    """completed-without-evidence must FAIL the mission_verdict gate."""
    result = run_verifier(
        "mission_verdict", "complete PASS + evidence",
        {"status": "complete", "verdict": "PASS",
         "completed_work": {"steps_completed": 2}, "evidence": []})
    assert result["ok"] is False
    assert "no real evidence" in result["detail"].lower()


def test_mission_verdict_rejects_executing_or_blocked():
    for payload in (
        {"status": "executing", "verdict": None,
         "completed_work": {"steps_completed": 0}, "evidence": []},
        {"status": "blocked", "verdict": "BLOCKED",
         "completed_work": {"steps_completed": 0}, "evidence": []},
    ):
        result = run_verifier("mission_verdict", "complete PASS", payload)
        assert result["ok"] is False


def test_mission_verdict_passes_only_with_real_files(tmp_path):
    ev_file = tmp_path / "proof.png"
    ev_file.write_bytes(b"\x89PNG\x0d\x0a\x1a\x0a")
    result = run_verifier(
        "mission_verdict", "complete PASS + evidence",
        {"status": "complete", "verdict": "PASS",
         "completed_work": {"steps_completed": 3},
         "evidence": [{"path": str(ev_file)}]})
    assert result["ok"] is True


def test_screenshot_missing_and_invalid(tmp_path):
    missing = run_verifier("screenshot_valid", "valid",
                           str(tmp_path / "nope.png"))
    assert missing["ok"] is False
    fake = tmp_path / "fake.png"
    fake.write_text("definitely not an image", encoding="utf-8")
    invalid = run_verifier("screenshot_valid", "valid", str(fake))
    assert invalid["ok"] is False


def test_screenshot_valid_with_real_png(tmp_path):
    try:
        from PIL import Image
    except Exception:
        pytest.skip("PIL unavailable")
    png = tmp_path / "real.png"
    Image.new("RGB", (1920, 1080), "black").save(png)
    result = run_verifier("screenshot_valid", "valid", str(png))
    assert result["ok"] is True
    bad_size = run_verifier("screenshot_valid", "valid", str(png),
                            {"expected_size": (1280, 720)})
    assert bad_size["ok"] is False


def test_stale_duplicate_detected(tmp_path):
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    a.write_bytes(b"\x89PNG-identical")
    b.write_bytes(b"\x89PNG-identical")
    result = run_verifier("no_stale_duplicate", "distinct", [str(a), str(b)])
    assert result["ok"] is False
    assert "duplicate" in result["detail"].lower()


def test_impossible_claim_rejected():
    result = run_verifier("truthful_claim",
                          "the mission created 12 blueprints", {})
    assert result["ok"] is False
    assert "no independent evidence" in result["detail"].lower()


def test_evidence_file_zero_size(tmp_path):
    empty = tmp_path / "ev.json"
    empty.write_text("", encoding="utf-8")
    result = run_verifier("evidence_file_ok", "file", str(empty))
    assert result["ok"] is False


def test_actor_count_and_members(tmp_path):
    ok = run_verifier("actor_count_ok", 166, 166)
    assert ok["ok"] is True
    bad = run_verifier("actor_count_ok", 166, 170)
    assert bad["ok"] is False
    present = run_verifier("list_members_present", ["AVIDO_Human_Master"],
                           ["AVIDO_Human_Master", "AVIDO_KeyLight"])
    assert present["ok"] is True
    missing = run_verifier("list_members_present", ["AVIDO_Human_Master"],
                           ["AVIDO_KeyLight"])
    assert missing["ok"] is False
    absent = run_verifier("list_members_absent", ["WhiteH"],
                          ["AVIDO_KeyLight"])
    assert absent["ok"] is True
    found = run_verifier("list_members_absent", ["WhiteH"],
                         ["WhiteH_Avatar"])
    assert found["ok"] is False


def test_video_file_ok(tmp_path):
    vid = tmp_path / "x.mp4"
    vid.write_bytes(b"ftypmp42" + b"\x00" * 2048)
    assert run_verifier("video_file_ok", "playable", str(vid))["ok"] is True
    tiny = tmp_path / "tiny.mp4"
    tiny.write_bytes(b"ftyp")
    assert run_verifier("video_file_ok", "playable", str(tiny))["ok"] is False


def test_health_ok_and_http_ok():
    assert run_verifier("health_ok", "ok", {"ok": True, "unreal": {},
                                            "ollama": {}})["ok"] is True
    assert run_verifier("health_ok", "ok", {"ok": True})["ok"] is False
    assert run_verifier("http_ok", "200", {"status": 200})["ok"] is True
    assert run_verifier("http_ok", "200", {"status": 500})["ok"] is False