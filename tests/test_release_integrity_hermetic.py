"""AIVIDO parallel QA — static release integrity checks.

Offline verification of the certified release artifacts:

  * every release report (reports/hq/*.json) parses as JSON
  * the polish-90 scorecard honors its contract (baseline 80, truthful
    score, branch, PASS/WARN/FAIL categories)
  * every evidence path referenced by the scorecard exists and PNGs are
    real PNG files
  * no "DEMO PASS" artifact is promoted as a LIVE/certified status
  * no credentials / private keys / API tokens in reports

Read-only. No live Unreal or backend access.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HQ = ROOT / "reports" / "hq"

SCORECARD = HQ / "POLISH_90_SCORECARD.json"
REPORT = HQ / "POLISH_90_REPORT.md"

ALLOWED_STATUSES = {"PASS", "WARN", "FAIL"}

SECRET_PATTERNS = [
    re.compile(r"(?i)\b(api[_-]?key|password|passwd|secret|authorization)\s*[:=]\s*[\"']?[A-Za-z0-9_\-]{8,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"),
]


def _iter_json_files():
    for p in sorted(HQ.glob("*.json")):
        yield p


class TestReportsParse:
    @pytest.mark.parametrize("path", list(HQ.glob("*.json")), ids=lambda p: p.name)
    def test_report_json_parses(self, path):
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig", errors="strict")
        assert json.loads(text) is not None


class TestPolishScorecardContract:
    def test_required_keys(self):
        d = json.loads(SCORECARD.read_text(encoding="utf-8-sig"))
        for key in ("mission", "certified_baseline", "truthful_score",
                    "target_achieved", "branch", "categories",
                    "regression_gate", "warnings", "proof_paths",
                    "critical_errors", "major_errors", "warnings_remaining"):
            assert key in d, f"scorecard missing key {key!r}"

    def test_baseline_and_score(self):
        d = json.loads(SCORECARD.read_text(encoding="utf-8-sig"))
        assert d["certified_baseline"] == 80
        assert isinstance(d["truthful_score"], int)
        assert 80 <= d["truthful_score"] <= 100
        assert isinstance(d["target_achieved"], bool)

    def test_branch_is_polish_90(self):
        d = json.loads(SCORECARD.read_text(encoding="utf-8-sig"))
        assert d["branch"] == "aivido/polish-90"

    def test_category_statuses_valid(self):
        d = json.loads(SCORECARD.read_text(encoding="utf-8-sig"))
        for name, cat in d["categories"].items():
            status = cat.get("status")
            assert status in ALLOWED_STATUSES, f"category {name}: bad status {status!r}"

    def test_regression_gate_keys(self):
        d = json.loads(SCORECARD.read_text(encoding="utf-8-sig"))
        gate = d["regression_gate"]
        for key in ("characters", "map_load", "map_save", "map_reopen",
                    "lighting_rebuild_warning", "idle_driver_start_stop_restore"):
            assert key in gate, f"regression gate missing {key!r}"


class TestEvidencePaths:
    def test_scorecard_evidence_paths_exist(self):
        d = json.loads(SCORECARD.read_text(encoding="utf-8-sig"))
        proof = d["proof_paths"]
        ev_dir = ROOT / proof["dir"]
        assert ev_dir.is_dir(), f"evidence dir missing: {proof['dir']}"
        for shot in proof["shots"]:
            p = ev_dir / shot
            assert p.exists(), f"missing evidence file: {proof['dir']}/{shot}"

    def test_png_evidence_is_real_png(self):
        d = json.loads(SCORECARD.read_text(encoding="utf-8-sig"))
        ev_dir = ROOT / d["proof_paths"]["dir"]
        for shot in d["proof_paths"]["shots"]:
            if shot.endswith(".png"):
                magic = (ev_dir / shot).read_bytes()[:8]
                assert magic == b"\x89PNG\r\n\x1a\n", f"{shot} is not a PNG"

    def test_report_references_evidence_and_scorecard_exists(self):
        text = REPORT.read_text(encoding="utf-8", errors="replace")
        assert "POLISH_90_EVIDENCE" in text, "report must reference the evidence dir"
        assert SCORECARD.exists(), "scorecard file must exist next to the report"


class TestNoDemoPromotedAsLive:
    def test_scorecard_not_demo(self):
        d = json.loads(SCORECARD.read_text(encoding="utf-8-sig"))
        for key, value in d.items():
            if isinstance(value, str) and "demo" in value.lower():
                pytest.fail(f"scorecard field {key!r} mentions demo: {value!r}")

    def test_final_qa_scorecard_overall_status_not_demo(self):
        p = HQ / "FINAL_QA_SCORECARD.json"
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8-sig"))
            status = d.get("qa_scorecard", {}).get("overall_status", "")
            assert "demo" not in status.lower(), f"overall_status is demo: {status!r}"

    def test_no_demo_pass_assertions_in_release_md(self):
        for p in [REPORT, HQ / "WORKER5_FINAL_INTEGRATION_HANDOFF.md"]:
            if p.exists():
                text = p.read_text(encoding="utf-8", errors="replace")
                assert "DEMO PASS" not in text, f"{p.name} asserts DEMO PASS"


class TestNoSecrets:
    @pytest.mark.parametrize("path", sorted(list(HQ.glob("*"))), ids=lambda p: p.name)
    def test_release_files_contain_no_secrets(self, path):
        if path.suffix not in (".md", ".json", ".txt"):
            return
        text = path.read_text(encoding="utf-8", errors="replace")
        hits = []
        for pat in SECRET_PATTERNS:
            for m in pat.finditer(text):
                hits.append(f"  {path.name}: {pat.pattern[:40]}... -> {m.group(0)[:40]!r}")
        assert not hits, "potential secret material in release reports:\n" + "\n".join(hits)