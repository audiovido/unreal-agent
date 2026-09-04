"""Step 7 regression tests: the speed optimizations must preserve behavior.

Covers:
  * vision providers are skipped when the deterministic verdict is decisive
    (clean above the decisive score, or any deterministic defect) and still
    run on ambiguous near-threshold frames
  * the release evaluate reuses precomputed metrics/score (no duplicate
    deterministic measure) with identical results
  * the adapter's quick capture-written confirmation

None of these tests need a live editor, a bridge, or a vision model.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import vision_provider  # noqa: E402
from core.vision_provider import VisionReview  # noqa: E402


def _fake_metrics(issues=None, overall=9.0):
    return types.SimpleNamespace(
        ok=True, issues=list(issues or []), head_clipped=False, stale=False,
        bands=None, roll_deg=0.0, mean_luma=120.0, pct_white=0.01,
        pct_black=0.10, entropy=6.5, std_luma=30.0, hash_md5_12="a" * 12,
        width=100, height=100, subject_coverage=0.35, subject_bbox=(0, 0, 1, 1),
        ui_screen_coverage=None, ui_bbox=None)


def _fake_score(overall):
    return types.SimpleNamespace(overall=float(overall))


def _spy_provider(calls):
    def provider(image_path):
        calls.append(image_path)
        return VisionReview(provider="spy", ok=True, score=9.0,
                            confidence=0.9, defects=[])
    return provider


class TestVisionProviderDecisiveSkip:
    def test_clean_high_score_skips_providers(self, monkeypatch):
        calls = []
        det = vision_provider.deterministic_review(
            "x.png", metrics=_fake_metrics(), score=_fake_score(8.9))
        monkeypatch.setattr(vision_provider, "deterministic_review",
                            lambda *a, **k: det)
        out = vision_provider.review_image(
            "x.png", providers=[_spy_provider(calls)],
            metrics=_fake_metrics(), score=_fake_score(8.9),
            decisive_score=8.5)
        assert calls == []
        assert out["provider_attempts"] == []
        assert out["ok"] is True
        assert out["score"] == pytest.approx(8.9)
        assert any("skipped" in w for w in out.get("warnings", []))

    def test_deterministic_defects_skip_providers(self, monkeypatch):
        calls = []
        det = vision_provider.deterministic_review(
            "x.png", metrics=_fake_metrics(issues=["HEAD_CROPPED"]),
            score=_fake_score(6.7))
        monkeypatch.setattr(vision_provider, "deterministic_review",
                            lambda *a, **k: det)
        out = vision_provider.review_image(
            "x.png", providers=[_spy_provider(calls)],
            metrics=_fake_metrics(issues=["HEAD_CROPPED"]),
            score=_fake_score(6.7), decisive_score=8.5)
        assert calls == []
        assert out["score"] == pytest.approx(6.7)
        assert "HEAD_CROPPED" in out["defects"]

    def test_ambiguous_frame_still_runs_providers(self, monkeypatch):
        calls = []
        det = vision_provider.deterministic_review(
            "x.png", metrics=_fake_metrics(), score=_fake_score(7.6))
        monkeypatch.setattr(vision_provider, "deterministic_review",
                            lambda *a, **k: det)
        out = vision_provider.review_image(
            "x.png", providers=[_spy_provider(calls)],
            metrics=_fake_metrics(), score=_fake_score(7.6),
            decisive_score=8.5)
        assert len(calls) == 1
        assert len(out["provider_attempts"]) == 1

    def test_default_keeps_legacy_behavior(self, monkeypatch):
        # decisive_score=None (the historic contract) must still run models
        calls = []
        det = vision_provider.deterministic_review(
            "x.png", metrics=_fake_metrics(), score=_fake_score(9.0))
        monkeypatch.setattr(vision_provider, "deterministic_review",
                            lambda *a, **k: det)
        out = vision_provider.review_image(
            "x.png", providers=[_spy_provider(calls)],
            metrics=_fake_metrics(), score=_fake_score(9.0))
        assert len(calls) == 1


class TestReleaseEvaluateCachedMetrics:
    def _evaluate(self, monkeypatch, measure_calls, score_calls):
        import assetlib.reports.unreal_coder_release_missions as rel

        def spy_measure(path, *a, **k):
            measure_calls.append(str(path))
            return _fake_metrics()

        def spy_score(m, *a, **k):
            score_calls.append(1)
            return _fake_score(8.9)

        import core.visual_acceptance as va
        monkeypatch.setattr(va, "measure", spy_measure)
        monkeypatch.setattr(va, "score", spy_score)
        monkeypatch.setattr(vision_provider, "get_configured_providers",
                            lambda: [])
        fn = rel._make_evaluate(bridge=None,
                                scene_locators=None)
        return fn

    def test_plain_path_measures_once(self, monkeypatch):
        m, s = [], []
        fn = self._evaluate(monkeypatch, m, s)
        out = fn({"path": "frame.png", "ok": True})
        assert len(m) == 1 and len(s) == 1
        assert out["score"] == pytest.approx(8.9)

    def test_cached_metrics_skip_duplicate_measure(self, monkeypatch):
        m, s = [], []
        fn = self._evaluate(monkeypatch, m, s)
        metrics = _fake_metrics()
        score = _fake_score(8.9)
        out = fn({"path": "frame.png", "ok": True,
                  "_metrics": metrics, "_score": score})
        assert m == [] and s == []  # no duplicate deterministic measure
        assert out["score"] == pytest.approx(8.9)
        assert out["defects"] == []

    def test_cached_result_equals_fresh_result(self, monkeypatch):
        """Both routes must produce identical score/defects."""
        m1, s1 = [], []
        fn1 = self._evaluate(monkeypatch, m1, s1)
        fresh = fn1({"path": "frame.png", "ok": True})
        m2, s2 = [], []
        fn2 = self._evaluate(monkeypatch, m2, s2)
        cached = fn2({"path": "frame.png", "ok": True,
                      "_metrics": _fake_metrics(), "_score": _fake_score(8.9)})
        assert fresh["score"] == cached["score"]
        assert fresh["defects"] == cached["defects"]


class TestAdapterWrittenConfirmation:
    def test_confirms_written_file_fast(self, tmp_path):
        from core.unreal_fix_adapter import UnrealFixAdapter
        ad = UnrealFixAdapter(bridge=None)
        p = tmp_path / "frame.png"
        p.write_bytes(b"x" * 1000)
        assert ad._confirm_written(p, size=1000, timeout=2.0) is True

    def test_missing_file_times_out(self, tmp_path):
        from core.unreal_fix_adapter import UnrealFixAdapter
        ad = UnrealFixAdapter(bridge=None)
        p = tmp_path / "never.png"
        assert ad._confirm_written(p, size=100, timeout=0.15) is False
