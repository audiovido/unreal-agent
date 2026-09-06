"""vision_provider.py — UNREAL CODER production visual reasoning (Phase B).

ONE generic provider abstraction for visual review:

    provider name -> callable(image_path) -> structured review dict

Design rules (release requirements):
- provider abstraction is GENERIC: no hard dependency on one model name
- local vision models supported (Ollama-compatible endpoints)
- remote vision models supported (OpenAI-compatible /chat/completions)
- deterministic image analysis remains the fallback AND cross-check
- vision provider failure NEVER crashes a mission (degrades, records warning)
- every review carries: score, visible defects, confidence,
  recommended repair actions and evidence references

Disagreement handling: when model judgment conflicts strongly with the
deterministic measurement, the disagreement is recorded, extra evidence is
attached, and the deterministic result wins on ties (no blind scene edits).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

REVIEW_PROMPT = """You are the visual QA reviewer for an autonomous Unreal Engine agent.

Review ONLY what is visible in this screenshot. Return JSON only:
{
  "score": 0.0-10.0,
  "visible_defects": ["short defect names like WHITE_CLIPPING, SUBJECT_TOO_DARK, UI_LOW_CONTRAST, CHEAP_PRIMITIVE_LOOK"],
  "confidence": 0.0-1.0,
  "summary": "one short sentence",
  "recommended_actions": ["concrete Unreal-side repair actions"]
}

Rules:
- Score 8+ means production-ready for the requested style; 6-7 acceptable; below 6 needs repair.
- Use defect names from this vocabulary when they apply: HEAD_CROPPED, SUBJECT_TOO_LARGE, SUBJECT_TOO_SMALL,
  BACKGROUND_OVEREXPOSED, SUBJECT_TOO_DARK, WHITE_CLIPPING, BLACK_CLIPPING, UI_TOO_SMALL, UI_LOW_CONTRAST,
  UI_OFF_SCREEN, BLACK_BAND, STALE_CAPTURE, EMPTY_ENVIRONMENT, CHEAP_PRIMITIVE_LOOK, CAMERA_ROLL.
- confidence below 0.5 means you are unsure (bad image, ambiguous style, unfamiliar content).
- Never invent hidden project state; judge only visible pixels.
"""


@dataclass
class VisionReview:
    """Structured result of one visual review (model OR deterministic)."""

    score: float = 0.0
    defects: List[str] = field(default_factory=list)
    confidence: float = 0.0
    summary: str = ""
    recommended_actions: List[str] = field(default_factory=list)
    provider: str = "none"
    model: str = ""
    ok: bool = False
    error: str = ""
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    latency_s: float = 0.0

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "VisionReview":
        """Rebuild a review from its serialized form (cache round-trips)."""
        return cls(
            score=float(data.get("score") or 0.0),
            defects=list(data.get("defects") or []),
            confidence=float(data.get("confidence") or 0.0),
            summary=str(data.get("summary") or ""),
            recommended_actions=list(data.get("recommended_actions") or []),
            provider=str(data.get("provider") or "none"),
            model=str(data.get("model") or ""),
            ok=bool(data.get("ok")),
            error=str(data.get("error") or ""),
            evidence=list(data.get("evidence") or []),
            latency_s=float(data.get("latency_s") or 0.0),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "score": round(self.score, 2),
            "defects": list(self.defects),
            "confidence": round(self.confidence, 3),
            "summary": self.summary,
            "recommended_actions": list(self.recommended_actions),
            "provider": self.provider,
            "model": self.model,
            "error": self.error,
            "evidence": list(self.evidence),
            "latency_s": round(self.latency_s, 2),
        }


# ---------------------------------------------------------------------------
# Review cache (Phase G — performance)
# Identical frames never re-pay the vision LLM round-trip: reviews are cached
# by frame content hash with a bounded TTL and size. Deterministic review
# ALWAYS runs fresh (cheap, ms); only the model round-trip is cached.
# ---------------------------------------------------------------------------

_REVIEW_CACHE: Dict[str, Dict[str, Any]] = {}
_REVIEW_CACHE_TTL_S = float(os.getenv("UNREAL_AGENT_REVIEW_CACHE_TTL", "900"))
_REVIEW_CACHE_MAX = int(os.getenv("UNREAL_AGENT_REVIEW_CACHE_MAX", "64"))
_REVIEW_LOCK = threading.Lock()


def _frame_hash(image_path: str) -> str:
    try:
        with open(image_path, "rb") as fh:
            return hashlib.md5(fh.read()).hexdigest()[:12]
    except OSError:
        return ""


def _review_cache_get(key: str) -> Optional[Dict[str, Any]]:
    if not key:
        return None
    with _REVIEW_LOCK:
        entry = _REVIEW_CACHE.get(key)
        if not entry:
            return None
        if time.time() - float(entry["at"]) > _REVIEW_CACHE_TTL_S:
            _REVIEW_CACHE.pop(key, None)
            return None
        return dict(entry["review"])


def _review_cache_put(key: str, review: Dict[str, Any]) -> None:
    if not key:
        return
    with _REVIEW_LOCK:
        if len(_REVIEW_CACHE) >= _REVIEW_CACHE_MAX:
            for old_key in sorted(
                _REVIEW_CACHE, key=lambda k: _REVIEW_CACHE[k]["at"])[:8]:
                _REVIEW_CACHE.pop(old_key, None)
        _REVIEW_CACHE[key] = {"at": time.time(), "review": dict(review)}


def review_cache_clear() -> None:
    """Drop all cached reviews (test/ops hook)."""
    with _REVIEW_LOCK:
        _REVIEW_CACHE.clear()


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

def _encode_image(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as fh:
            return base64.b64encode(fh.read()).decode("ascii")
    except Exception:
        return None


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Best-effort JSON extraction from a model reply (tolerates fences)."""
    if not text:
        return None
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(cleaned[start:end + 1])
        return data if isinstance(data, dict) else None
    except Exception:
        return None


_LOCAL_CACHE: Dict[str, Any] = {"checked": False, "models": []}


def ollama_models(base_url: Optional[str] = None) -> List[str]:
    """List installed local models (cached). Empty when Ollama is down."""
    base = (base_url or os.getenv(
        "UNREAL_AGENT_OLLAMA_URL", "http://127.0.0.1:11434")).rstrip("/")
    if "/api" in base:
        base = base.split("/api")[0]
    if _LOCAL_CACHE["checked"]:
        return list(_LOCAL_CACHE["models"])
    try:
        import requests
        response = requests.get(f"{base}/api/tags", timeout=4)
        response.raise_for_status()
        models = [
            str(m.get("name") or m.get("model"))
            for m in response.json().get("models", [])
            if m.get("name") or m.get("model")
        ]
        _LOCAL_CACHE["models"] = models
    except Exception:
        _LOCAL_CACHE["models"] = []
    _LOCAL_CACHE["checked"] = True
    return list(_LOCAL_CACHE["models"])


def make_local_provider(model: Optional[str] = None,
                        base_url: Optional[str] = None,
                        timeout: float = 300.0) -> Callable[[str], VisionReview]:
    """Local Ollama-compatible vision provider (no hard model name)."""
    def review(image_path: str) -> VisionReview:
        started = time.time()
        model_name = model or os.getenv("UNREAL_AGENT_VISION_MODEL", "")
        if not model_name:
            installed = ollama_models(base_url)
            model_name = next(
                (m for m in installed if "vl" in m.lower() or "vision" in m.lower()
                 or "llava" in m.lower()),
                installed[0] if installed else "")
        result = VisionReview(provider="local_ollama", model=model_name)
        image_b64 = _encode_image(image_path)
        if not image_b64:
            result.error = "image unreadable"
            result.latency_s = time.time() - started
            return result
        if not model_name:
            result.error = "no local vision model installed"
            result.latency_s = time.time() - started
            return result
        base = (base_url or os.getenv(
            "UNREAL_AGENT_OLLAMA_URL", "http://127.0.0.1:11434")).rstrip("/")
        if "/api" in base:
            base = base.split("/api")[0]
        body = {
            "model": model_name,
            "stream": False,
            "options": {"temperature": 0},
            "messages": [{
                "role": "user",
                "content": REVIEW_PROMPT,
                "images": [image_b64],
            }],
        }
        try:
            import requests
            response = requests.post(f"{base}/api/chat", json=body,
                                     timeout=timeout)
            response.raise_for_status()
            content = str(response.json().get("message", {}).get("content", ""))
            data = _extract_json(content)
            if data is None:
                result.error = "malformed model response"
            else:
                result.ok = True
                result.score = float(data.get("score") or 0.0)
                result.defects = [str(d) for d in (data.get("visible_defects") or [])][:12]
                result.confidence = float(data.get("confidence") or 0.5)
                result.summary = str(data.get("summary") or "")[:300]
                result.recommended_actions = [
                    str(a) for a in (data.get("recommended_actions") or [])][:8]
        except Exception as exc:
            result.error = f"{type(exc).__name__}: {str(exc)[:160]}"
        result.latency_s = time.time() - started
        return result
    return review


def make_remote_provider(model: Optional[str] = None,
                         base_url: Optional[str] = None,
                         api_key: Optional[str] = None,
                         timeout: float = 120.0) -> Callable[[str], VisionReview]:
    """Remote OpenAI-compatible vision provider (/chat/completions)."""
    def review(image_path: str) -> VisionReview:
        started = time.time()
        result = VisionReview(provider="remote", model=model or "")
        image_b64 = _encode_image(image_path)
        if not image_b64:
            result.error = "image unreadable"
            result.latency_s = time.time() - started
            return result
        url = base_url or os.getenv("UNREAL_AGENT_REMOTE_VISION_URL", "")
        key = api_key or os.getenv("UNREAL_AGENT_REMOTE_API_KEY", "")
        model_name = model or os.getenv("UNREAL_AGENT_VISION_MODEL", "")
        if not url or not key or not model_name:
            result.error = "remote vision provider not configured"
            result.latency_s = time.time() - started
            return result
        body = {
            "model": model_name,
            "temperature": 0,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": REVIEW_PROMPT},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/png;base64,{image_b64}"}},
                ],
            }],
        }
        try:
            import requests
            response = requests.post(
                url, json=body, timeout=timeout,
                headers={"Authorization": f"Bearer {key}"})
            response.raise_for_status()
            content = (response.json().get("choices") or [{}])[0].get(
                "message", {}).get("content", "")
            data = _extract_json(str(content))
            if data is None:
                result.error = "malformed model response"
            else:
                result.ok = True
                result.score = float(data.get("score") or 0.0)
                result.defects = [str(d) for d in (data.get("visible_defects") or [])][:12]
                result.confidence = float(data.get("confidence") or 0.5)
                result.summary = str(data.get("summary") or "")[:300]
                result.recommended_actions = [
                    str(a) for a in (data.get("recommended_actions") or [])][:8]
        except Exception as exc:
            result.error = f"{type(exc).__name__}: {str(exc)[:160]}"
        result.latency_s = time.time() - started
        return result
    return review


def make_disabled_provider(reason: str = "provider disabled") -> Callable[[str], VisionReview]:
    def review(image_path: str) -> VisionReview:
        return VisionReview(provider="none", ok=False, error=reason)
    return review


def get_configured_providers() -> List[Callable[[str], VisionReview]]:
    """All configured providers in priority order (remote first when set)."""
    providers: List[Callable[[str], VisionReview]] = []
    if os.getenv("UNREAL_AGENT_REMOTE_VISION_URL") and \
            os.getenv("UNREAL_AGENT_REMOTE_API_KEY"):
        providers.append(make_remote_provider())
    if ollama_models():
        providers.append(make_local_provider())
    return providers


# ---------------------------------------------------------------------------
# Deterministic fallback + cross-check
# ---------------------------------------------------------------------------

def deterministic_review(image_path: str,
                         metrics: Any = None,
                         score: Any = None) -> VisionReview:
    """Deterministic image measurement as fallback/cross-check.

    `metrics`/`score` accept an already-measured VisualMetrics/VisualScore to
    avoid double work; when omitted the image is measured here.
    """
    review = VisionReview(provider="deterministic", confidence=1.0)
    if metrics is None or score is None:
        from core.visual_acceptance import measure, score as score_fn
        metrics = measure(image_path)
        score = score_fn(metrics)
    if not getattr(metrics, "ok", False):
        review.error = "image unreadable by deterministic measurement"
        return review
    review.ok = True
    review.score = float(score.overall)
    review.defects = list(getattr(metrics, "issues", []))
    review.summary = (
        f"measured luma={getattr(metrics, 'mean_luma', -1):.0f} "
        f"entropy={getattr(metrics, 'entropy', -1):.1f}")
    review.evidence.append({
        "type": "deterministic_metrics",
        "path": image_path,
        "mean_luma": getattr(metrics, "mean_luma", None),
        "pct_white": getattr(metrics, "pct_white", None),
        "pct_black": getattr(metrics, "pct_black", None),
        "entropy": getattr(metrics, "entropy", None),
    })
    if review.defects:
        from core.visual_director import defect_to_action
        review.recommended_actions = [
            defect_to_action(d) for d in review.defects[:6]]
    return review


# ---------------------------------------------------------------------------
# Review pipeline: model first, deterministic fallback + cross-check
# ---------------------------------------------------------------------------

DEFECT_VOCABULARY = {
    "HEAD_CROPPED", "SUBJECT_TOO_LARGE", "SUBJECT_TOO_SMALL",
    "BACKGROUND_OVEREXPOSED", "SUBJECT_TOO_DARK", "WHITE_CLIPPING",
    "BLACK_CLIPPING", "UI_TOO_SMALL", "UI_LOW_CONTRAST", "UI_OFF_SCREEN",
    "BLACK_BAND", "STALE_CAPTURE", "EMPTY_ENVIRONMENT",
    "CHEAP_PRIMITIVE_LOOK", "CAMERA_ROLL",
}

STRONG_CONFLICT_DELTA = 2.5


def resolve_disagreement(det: VisionReview,
                         model: VisionReview) -> Dict[str, Any]:
    """Compare model judgment with deterministic measurement.

    Returns a disagreement record; when the conflict is strong the
    deterministic verdict wins and extra evidence is required before any
    scene modification.
    """
    record = {
        "detected": False,
        "delta": 0.0,
        "resolution": "model",
        "note": "",
    }
    if not det.ok or not model.ok:
        return record
    delta = abs(float(det.score) - float(model.score))
    record["delta"] = round(delta, 2)
    model_defects = {d.upper() for d in model.defects}
    vocab_defects = {d for d in model_defects if d in DEFECT_VOCABULARY}
    invented = model_defects - vocab_defects
    if delta >= STRONG_CONFLICT_DELTA:
        record["detected"] = True
        record["resolution"] = "deterministic_wins"
        record["note"] = (
            f"model {model.score:.1f} vs deterministic {det.score:.1f}; "
            "deterministic verdict used; additional evidence required "
            "before scene changes")
    elif invented:
        record["detected"] = True
        record["resolution"] = "defects_filtered"
        record["note"] = (
            f"model invented non-vocabulary defects {sorted(invented)[:4]}; "
            "filtered to known vocabulary")
    return record


def review_image(image_path: str,
                 providers: Optional[List[Callable[[str], VisionReview]]] = None,
                 metrics: Any = None,
                 score: Any = None,
                 decisive_score: Optional[float] = None) -> Dict[str, Any]:
    """Production visual review of one captured frame.

    Pipeline:
      1. try each configured vision provider (bounded, never raises)
         UNLESS `decisive_score` is set and the deterministic verdict is
         already decisive: clean-and-above-the-score or any deterministic
         defect/structural flag.  In those cases the deterministic review is
         authoritative (the model verdict was historically always overridden
         by deterministic_wins), so the provider round-trip is skipped.
         Ambiguous frames (no defects, deterministic score below the
         decisive threshold) still get the full model cross-check.
      2. deterministic measurement always runs (fallback AND cross-check)
      3. blend: model score weighted by its confidence; deterministic
         wins on strong disagreement
      4. result carries score, defects, confidence, actions, evidence

    Never raises. A mission cannot crash because vision is down.
    """
    started = time.time()
    det = deterministic_review(image_path, metrics=metrics, score=score)
    warnings: List[str] = []
    attempts: List[Dict[str, Any]] = []

    # ---- decisive-verdict shortcut (only when explicitly requested) -----
    skip_models = False
    if decisive_score is not None and det.ok:
        ambiguous = (
            not det.defects
            and float(det.score or 0.0) < float(decisive_score)
            and not getattr(metrics, "head_clipped", False)
            and not getattr(metrics, "stale", False)
            and not getattr(metrics, "bands", None)
            and float(getattr(metrics, "roll_deg", 0.0) or 0.0) <= 3.5)
        skip_models = not ambiguous
        if skip_models:
            warnings.append(
                f"vision providers skipped: deterministic verdict decisive "
                f"(score {det.score:.2f}, defects {len(det.defects)})")

    chosen: Optional[VisionReview] = None
    disagreement: Dict[str, Any] = {"detected": False, "resolution": "deterministic",
                                    "note": "", "delta": 0.0}
    # Phase G: when this exact frame was already reviewed by a vision model,
    # reuse that verdict instead of paying the LLM round-trip again. Only
    # applies when providers WOULD run (not decisive-skipped); the cheap
    # deterministic measurement always re-runs.
    cached_review: Optional[Dict[str, Any]] = None
    frame_key = ""
    if providers and not skip_models:
        frame_key = _frame_hash(image_path)
        cached_review = _review_cache_get(frame_key)
        if cached_review is not None:
            warnings.append(
                "vision review served from frame-content cache "
                "(identical pixels, no model round-trip)")

    if cached_review is not None:
        model_review = VisionReview.from_dict(cached_review)
        attempts.append({"provider": "review_cache", "model": "cached",
                         "ok": True, "latency_s": 0.0})
        disagreement = resolve_disagreement(det, model_review)
        if disagreement["resolution"] == "deterministic_wins":
            warnings.append(f"VISION_DISAGREEMENT: {disagreement['note']}")
            chosen = det
        else:
            model_review.defects = [
                d for d in model_review.defects
                if str(d).upper() in DEFECT_VOCABULARY]
            chosen = model_review
    else:
        for provider in (providers or []):
            if skip_models:
                break
            try:
                model_review = provider(image_path)
            except Exception as exc:  # provider crash must not propagate
                attempts.append({"provider": "unknown", "ok": False,
                                 "error": f"{type(exc).__name__}: {str(exc)[:120]}"})
                continue
            attempts.append({
                "provider": model_review.provider, "model": model_review.model,
                "ok": model_review.ok, "error": model_review.error,
                "latency_s": round(model_review.latency_s, 2),
            })
            if not model_review.ok:
                warnings.append(
                    f"vision provider '{model_review.provider}' unavailable: "
                    f"{model_review.error}")
                continue
            if float(model_review.confidence) < 0.35:
                warnings.append(
                    f"vision provider '{model_review.provider}' low confidence "
                    f"({model_review.confidence:.2f}); cross-checking with "
                    "deterministic measurement")
                continue
            raw_review = model_review.to_dict()
            disagreement = resolve_disagreement(det, model_review)
            if disagreement["resolution"] == "deterministic_wins":
                warnings.append(f"VISION_DISAGREEMENT: {disagreement['note']}")
                chosen = det
            else:
                # Non-vocabulary defects cannot map to a repair action: drop
                # them from the actionable list (kept in the raw review only).
                model_review.defects = [
                    d for d in model_review.defects
                    if str(d).upper() in DEFECT_VOCABULARY]
                chosen = model_review
            _review_cache_put(frame_key, raw_review)
            break

    if chosen is None:
        chosen = det
        if det.ok and providers:
            pass  # deterministic fallback already recorded
        elif not det.ok:
            warnings.append("no vision provider available and deterministic "
                            "measurement failed; visual gate cannot pass")

    if disagreement.get("detected"):
        chosen.evidence.append({
            "type": "vision_disagreement", "delta": disagreement["delta"],
            "resolution": disagreement["resolution"],
            "note": disagreement["note"],
        })

    result = chosen.to_dict()
    result["warnings"] = warnings
    result["provider_attempts"] = attempts
    result["disagreement"] = disagreement
    result["deterministic_cross_check"] = det.to_dict()
    result["total_latency_s"] = round(time.time() - started, 2)
    result["review_source"] = (
        "frame_cache" if cached_review is not None
        else ("deterministic_only" if not providers or skip_models
              else "provider"))
    return result
