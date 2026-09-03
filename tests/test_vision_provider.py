"""UNREAL CODER — Phase B: production visual reasoning tests.

Covers the vision provider abstraction: available/unavailable/malformed/
low-confidence/conflicting providers, deterministic fallback and
disagreement handling.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.vision_provider import (
    VisionReview,
    deterministic_review,
    make_disabled_provider,
    make_local_provider,
    make_remote_provider,
    resolve_disagreement,
    review_image,
)


@pytest.fixture(scope="module")
def real_image(tmp_path_factory):
    """A synthetic non-trivial frame so deterministic measurement succeeds."""
    from PIL import Image, ImageDraw
    path = tmp_path_factory.mktemp("frames") / "frame.png"
    img = Image.new("RGB", (640, 360), (60, 80, 110))
    draw = ImageDraw.Draw(img)
    draw.rectangle([80, 60, 300, 320], fill=(150, 160, 180))
    draw.rectangle([420, 80, 600, 300], fill=(30, 34, 44))
    for i in range(0, 640, 16):
        draw.line([(i, 0), (i, 359)], fill=(70 + i % 40, 90, 110))
    img.save(path)
    return str(path)


class TestProviderAbstraction:
    def test_local_provider_malformed_response(self, real_image):
        """Malformed model output -> not ok, no crash, error recorded."""
        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"message": {"content": "this is not json at all"}}

        provider = make_local_provider(model="fake-vl")
        result = VisionReview(provider="local_ollama")
        import core.vision_provider as vp
        called = {}

        def fake_encode(path):
            called["encoded"] = True
            return "aGVsbG8="

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(vp, "_encode_image", fake_encode)
            mp.setattr("requests.post", lambda *a, **k: FakeResponse())
            review = provider(real_image)
        assert review.ok is False
        assert "malformed" in review.error
        assert review.provider == "local_ollama"

    def test_local_provider_unreachable(self, real_image):
        """Vision down -> structured failure, never an exception."""
        import requests as requests_mod
        provider = make_local_provider(model="fake-vl")

        def boom(*a, **k):
            raise requests_mod.ConnectionError("ollama down")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(vp_encode := __import__(
                "core.vision_provider", fromlist=["_encode_image"]),
                "_encode_image", lambda p: "aGVsbG8=")
            mp.setattr("requests.post", boom)
            review = provider(real_image)
        assert review.ok is False
        assert "ConnectionError" in review.error

    def test_remote_provider_unconfigured(self, real_image, monkeypatch):
        monkeypatch.delenv("UNREAL_AGENT_REMOTE_VISION_URL", raising=False)
        monkeypatch.delenv("UNREAL_AGENT_REMOTE_API_KEY", raising=False)
        provider = make_remote_provider()
        review = provider(real_image)
        assert review.ok is False
        assert "not configured" in review.error

    def test_disabled_provider(self, real_image):
        review = make_disabled_provider("off")(real_image)
        assert review.ok is False
        assert review.error == "off"


class TestDeterministicFallback:
    def test_deterministic_review_scores_real_image(self, real_image):
        review = deterministic_review(real_image)
        assert review.ok is True
        assert review.provider == "deterministic"
        assert 0.0 <= review.score <= 10.0
        assert review.confidence == 1.0
        assert review.evidence

    def test_deterministic_review_bad_path(self):
        review = deterministic_review(str(ROOT / "no_such_frame.png"))
        assert review.ok is False
        assert "unreadable" in review.error


class TestReviewPipeline:
    def test_vision_unavailable_falls_back(self, real_image):
        result = review_image(
            real_image, providers=[make_disabled_provider("down")])
        assert result["ok"] is True
        assert result["provider"] == "deterministic"
        assert any("unavailable" in w for w in result["warnings"])

    def test_vision_available_model_wins_when_agreeing(self, real_image):
        det = deterministic_review(real_image)

        def agreeing_provider(path):
            return VisionReview(
                provider="local_ollama", model="agree-vl", ok=True,
                score=max(0.0, det.score - 0.4), confidence=0.9,
                defects=["CHEAP_PRIMITIVE_LOOK"])

        result = review_image(real_image, providers=[agreeing_provider])
        assert result["provider"] == "local_ollama"
        assert result["disagreement"]["detected"] is False
        assert "CHEAP_PRIMITIVE_LOOK" in result["defects"]
        assert result["deterministic_cross_check"]["ok"] is True

    def test_low_confidence_cross_checks_deterministic(self, real_image):
        def shy_provider(path):
            return VisionReview(provider="local_ollama", ok=True,
                                score=9.5, confidence=0.2)

        result = review_image(real_image, providers=[shy_provider])
        assert result["provider"] == "deterministic"
        assert any("low confidence" in w for w in result["warnings"])

    def test_conflicting_provider_deterministic_wins(self, real_image):
        """Strong disagreement: deterministic verdict wins, recorded."""
        def conflicting_provider(path):
            return VisionReview(provider="local_ollama", ok=True,
                                score=9.8, confidence=0.95)

        result = review_image(real_image, providers=[conflicting_provider])
        assert result["disagreement"]["detected"] is True
        assert result["disagreement"]["resolution"] == "deterministic_wins"
        assert result["provider"] == "deterministic"
        assert result["evidence"] and any(
            e.get("type") == "vision_disagreement"
            for e in result["evidence"])
        assert any("VISION_DISAGREEMENT" in w for w in result["warnings"])

    def test_invented_defects_filtered(self, real_image):
        det = deterministic_review(real_image)

        def dreamer(path):
            # Score close to the deterministic value so only the defect
            # filter triggers (not the strong score conflict).
            return VisionReview(
                provider="local_ollama", ok=True,
                score=det.score + 0.1, confidence=0.8,
                defects=["GRUMPY_LIGHTING", "WHITE_CLIPPING"])

        result = review_image(real_image, providers=[dreamer])
        assert result["disagreement"]["resolution"] == "defects_filtered"
        assert "WHITE_CLIPPING" in result["defects"]
        assert "GRUMPY_LIGHTING" not in result["defects"]

    def test_provider_crash_never_propagates(self, real_image):
        def exploding(path):
            raise RuntimeError("provider exploded")

        result = review_image(real_image, providers=[exploding])
        assert result["ok"] is True
        assert result["provider"] == "deterministic"
        assert any("exploded" in str(a.get("error"))
                   for a in result["provider_attempts"])

    def test_no_providers_configured(self, real_image):
        result = review_image(real_image, providers=None)
        assert result["ok"] is True
        assert result["provider"] == "deterministic"

    def test_review_carries_contract_fields(self, real_image):
        result = review_image(
            real_image, providers=[make_disabled_provider("x")])
        for key in ("score", "defects", "confidence", "recommended_actions",
                    "provider", "evidence"):
            assert key in result, key


class TestGetConfiguredProviders:
    def test_returns_list_never_raises(self):
        providers = __import__("core.vision_provider", fromlist=[
            "get_configured_providers"]).get_configured_providers()
        assert isinstance(providers, list)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
