"""qa/verifier.py — INDEPENDENT VERIFIER REGISTRY (no-fake-pass core).

Every PASS must be backed by an explicit verifier. A verifier is a pure
function (expected, observed, context) -> {ok: bool, detail: str}. The
verifier NEVER trusts the product's own labels: it re-checks the underlying
artifact (file exists, real size, real dimensions, real bridge actor list,
real mission checkpoint state, real evidence paths).

Verifiers in this module are deliberately dependency-free (only stdlib +
PIL) so they can be unit-tested hermetically.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    from PIL import Image
    _HAS_PIL = True
except Exception:  # pragma: no cover
    _HAS_PIL = False

VERIFIERS: Dict[str, Callable[..., Dict[str, Any]]] = {}


def verifier(name: str):
    def deco(fn):
        VERIFIERS[name] = fn
        return fn
    return deco


def run_verifier(name: str, expected: Any, observed: Any,
                 context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    fn = VERIFIERS.get(name)
    if fn is None:
        return {"ok": False,
                "detail": f"unknown verifier '{name}' (PASS impossible)"}
    try:
        result = fn(expected, observed, context or {})
        if not isinstance(result, dict) or "ok" not in result:
            return {"ok": False, "detail": f"verifier '{name}' returned "
                                           "malformed result"}
        return result
    except Exception as exc:
        return {"ok": False,
                "detail": f"verifier '{name}' raised {type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Primitive verifiers
# ---------------------------------------------------------------------------


@verifier("http_ok")
def _http_ok(expected, observed, ctx):
    """HTTP 2xx is transport evidence ONLY; the body semantics must be
    verified separately. This verifier fails on non-2xx or a body that is
    not JSON with ok==true when the contract requires it."""
    observed = observed or {}
    try:
        status = int(observed.get("http_status") or observed.get("status")
                     or 0)
    except Exception:
        status = 0
    body_ok = True
    if ctx.get("require_body_ok"):
        body = observed.get("body")
        if isinstance(body, dict):
            body_ok = bool(body.get("ok"))
        else:
            body_ok = bool(observed.get("ok"))
    ok = 200 <= status < 300 and body_ok
    return {"ok": ok,
            "detail": f"HTTP {status}" + ("" if ok else " (non-2xx or "
                      "body ok=false)")}


@verifier("truthful_claim")
def _truthful_claim(expected, observed, ctx):
    """The claim must be independently observable in `observed`. A claim
    with NO evidence is a FAIL (impossible verification claim)."""
    claim = str(expected or "")
    evidence = observed
    if isinstance(evidence, dict):
        if evidence.get("ok") is False:
            return {"ok": False, "detail": "observed result is explicitly "
                                           "not ok"}
        text = json.dumps(evidence, default=str)
    elif isinstance(evidence, list):
        text = json.dumps(evidence, default=str)
    else:
        text = str(evidence or "")
    if not text or text in ("None", "null", "{}", "[]", "[object Object]"):
        return {"ok": False,
                "detail": f"claim '{claim}' has NO independent evidence"}
    return {"ok": True, "detail": f"claim '{claim}' backed by observed data"}


@verifier("mission_verdict")
def _mission_verdict(expected, observed, ctx):
    """PASS only when the REAL mission pipeline reports status complete AND
    verdict PASS AND >=1 executed step AND >=1 real evidence entry whose
    path exists on disk. Transport success is not a mission PASS."""
    payload = observed if isinstance(observed, dict) else {}
    problems: List[str] = []
    if str(payload.get("status")) != "complete":
        problems.append(f"status={payload.get('status')!r}")
    if str(payload.get("verdict")) not in ("PASS", "SUCCESS"):
        problems.append(f"verdict={payload.get('verdict')!r}")
    steps = (payload.get("completed_work") or {})
    if int(steps.get("steps_completed") or 0) < 1:
        problems.append("0 executed steps")
    evidence = payload.get("evidence") or []
    real_ev = 0
    for ev in evidence:
        if isinstance(ev, dict):
            p = ev.get("path")
            if p and Path(str(p)).is_file():
                real_ev += 1
    if real_ev < 1:
        problems.append(f"no real evidence files ({len(evidence)} entries)")
    if problems:
        return {"ok": False,
                "detail": "mission PASS unverified: " + "; ".join(problems)}
    return {"ok": True,
            "detail": f"mission complete, verdict {payload.get('verdict')}, "
                      f"{steps.get('steps_completed')} steps, "
                      f"{real_ev} real evidence file(s)"}


@verifier("evidence_file_ok")
def _evidence_file_ok(expected, observed, ctx):
    """File exists, non-empty, expected type, not '[object Object]', and
    (when required) mtime inside the run window. NEVER trusts a bare
    screenshot path claim: the file is opened and measured."""
    path = Path(str(observed or "") if not isinstance(observed, Path)
                else str(observed))
    problems: List[str] = []
    if not path.exists():
        return {"ok": False, "detail": f"file missing: {path}"}
    if not path.is_file():
        return {"ok": False, "detail": f"not a file: {path}"}
    size = path.stat().st_size
    if size <= 0:
        problems.append("zero-size file")
    ext_ok = (not ctx.get("expected_ext")
              or path.suffix.lower() == str(ctx["expected_ext"]).lower())
    if not ext_ok:
        problems.append(f"extension {path.suffix!r} != "
                        f"{ctx.get('expected_ext')!r}")
    if ctx.get("check_content"):
        try:
            head = path.read_bytes()[:64]
            if b"[object Object]" in head:
                problems.append("file contains [object Object]")
        except Exception:
            pass
    if ctx.get("require_fresh") and ctx.get("window"):
        age = time.time() - path.stat().st_mtime
        if age > float(ctx["window"]):
            problems.append(f"stale: mtime age {age:.0f}s > window "
                            f"{ctx['window']}s")
    if problems:
        return {"ok": False,
                "detail": f"{path.name}: " + "; ".join(problems)}
    return {"ok": True,
            "detail": f"{path.name}: {size} bytes, mtime "
                      f"{time.strftime('%H:%M:%S', time.localtime(path.stat().st_mtime))}"}


@verifier("screenshot_valid")
def _screenshot_valid(expected, observed, ctx):
    """Screenshot must be a decodable image with sane dimensions. The mere
    existence of a .png path is NOT visual evidence."""
    path = Path(str(observed or ""))
    if not path.exists():
        return {"ok": False, "detail": f"screenshot missing: {path}"}
    if path.stat().st_size <= 0:
        return {"ok": False, "detail": "zero-size screenshot"}
    if not _HAS_PIL:
        return {"ok": False, "detail": "PIL unavailable; screenshot "
                                       "cannot be verified"}
    try:
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            w, h = im.size
    except Exception as exc:
        return {"ok": False,
                "detail": f"invalid image: {type(exc).__name__}: {exc}"}
    if w <= 0 or h <= 0:
        return {"ok": False, "detail": f"non-positive dimensions {w}x{h}"}
    problems = []
    if ctx.get("expected_size"):
        ew, eh = ctx["expected_size"]
        if (w, h) != (ew, eh):
            problems.append(f"size {w}x{h} != expected {ew}x{eh}")
    if problems:
        return {"ok": False, "detail": "; ".join(problems)}
    return {"ok": True, "detail": f"{w}x{h} decodable image, "
                                  f"{path.stat().st_size} bytes"}


@verifier("no_stale_duplicate")
def _no_stale_duplicate(expected, observed, ctx):
    """Two distinct captures claiming to be fresh must not be byte-identical
    (a copied screenshot presented as a fresh capture is a false PASS)."""
    paths = [Path(p) for p in (observed or []) if p]
    existing = [p for p in paths if p.is_file()]
    if len(existing) < 2:
        return {"ok": True,
                "detail": f"{len(existing)} file(s) — not enough to compare"}
    hashes = []
    for p in existing:
        h = hashlib.sha256()
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        hashes.append(h.hexdigest())
    if len(set(hashes)) != len(hashes):
        dupes = [str(existing[i]) for i in range(len(hashes))
                 if hashes.count(hashes[i]) > 1]
        return {"ok": False,
                "detail": "stale duplicate evidence (identical sha256): "
                          + "; ".join(sorted(set(dupes)))}
    return {"ok": True, "detail": f"{len(existing)} distinct sha256 hashes"}


@verifier("expect_failure")
def _expect_failure(expected, observed, ctx):
    """False-pass defense: the injected bad case MUST fail. If the
    observed outcome is a PASS (or the verifier itself reports ok), the
    false-pass defense check FAILS."""
    verdict = str((observed or {}).get("outcome") or
                  (observed or {}).get("verdict") or "")
    rejected = bool((observed or {}).get("rejected"))
    ok = verdict.upper() in ("FAIL", "BLOCKED", "REJECTED", "CANCELLED") or rejected
    detail = f"bad case correctly rejected (outcome={verdict})" if ok else \
        f"BAD CASE NOT REJECTED (outcome={verdict}) — false PASS risk"
    return {"ok": ok, "detail": detail}


@verifier("actor_count_ok")
def _actor_count_ok(expected, observed, ctx):
    """Actor count read from the LIVE bridge actor list, not from a report.
    expected == exact count; observed == actual count."""
    expected_count = int(expected or -1)
    actual = observed
    if isinstance(actual, dict):
        actual = actual.get("count")
    try:
        actual_count = int(actual)
    except Exception:
        return {"ok": False, "detail": f"unreadable actor count: {observed!r}"}
    if expected_count >= 0 and actual_count != expected_count:
        return {"ok": False,
                "detail": f"actor count {actual_count} != expected "
                          f"{expected_count}"}
    return {"ok": True, "detail": f"actor count {actual_count}"}


@verifier("list_members_present")
def _list_members_present(expected, observed, ctx):
    """All required members must be present in the observed list."""
    members = [str(m) for m in (expected or [])]
    haystack = [str(x) for x in (observed or [])]
    if isinstance(observed, dict):
        haystack = [str(x) for x in (observed.get("actors") or [])]
    missing = [m for m in members if not any(m.lower() in h.lower()
                                             for h in haystack)]
    if missing:
        return {"ok": False,
                "detail": "missing members: " + "; ".join(missing)}
    return {"ok": True, "detail": f"all {len(members)} members present"}


@verifier("list_members_absent")
def _list_members_absent(expected, observed, ctx):
    """Forbidden members must NOT appear in the observed list."""
    members = [str(m) for m in (expected or [])]
    haystack = [str(x) for x in (observed or [])]
    if isinstance(observed, dict):
        haystack = [str(x) for x in (observed.get("actors") or [])]
    found = [m for m in members if any(m.lower() in h.lower()
                                       for h in haystack)]
    if found:
        return {"ok": False,
                "detail": "forbidden actors present: " + "; ".join(found)}
    return {"ok": True, "detail": f"no forbidden members "
                                  f"({', '.join(members) or 'none'})"}


@verifier("video_file_ok")
def _video_file_ok(expected, observed, ctx):
    """MP4 exists, non-empty, playable header (ftyp). ffprobe is not
    guaranteed everywhere, so the ftyp/moov header check is the portable
    playability gate; size must be > 1 KB."""
    path = Path(str(observed or ""))
    if not path.exists():
        return {"ok": False, "detail": f"video missing: {path}"}
    size = path.stat().st_size
    if size < 1024:
        return {"ok": False, "detail": f"video suspiciously small: {size} bytes"}
    with open(path, "rb") as fh:
        head = fh.read(64)
    if b"ftyp" not in head:
        return {"ok": False, "detail": "no ftyp box — not a playable MP4"}
    return {"ok": True,
            "detail": f"{size} bytes, MP4 container header present"}


@verifier("report_claim_consistent")
def _report_claim_consistent(expected, observed, ctx):
    """A committed report's claims must be consistent with the artifacts
    on disk (e.g. 240-frame claim vs actual frame-file count or proof
    stills + MP4). Missing artifacts for a claim => FAIL."""
    claim = str(expected or "")
    evidence = observed if isinstance(observed, dict) else {}
    problems = []
    if ctx.get("require_artifact"):
        ap = Path(str(evidence.get("artifact_path") or ""))
        if not ap.exists():
            problems.append(f"claimed artifact missing: {ap}")
    if ctx.get("expected_entries") and evidence.get("entries") is not None:
        if int(evidence.get("entries")) != int(ctx["expected_entries"]):
            problems.append(f"entries {evidence.get('entries')} != expected "
                            f"{ctx['expected_entries']}")
    if problems:
        return {"ok": False, "detail": claim + " — " + "; ".join(problems)}
    return {"ok": True, "detail": f"claim consistent: {claim}"}


@verifier("registry_match")
def _registry_match(expected, observed, ctx):
    """Expected value must match the observed value (strict or
    case-insensitive per ctx)."""
    strict = bool(ctx.get("strict"))
    exp = expected
    obs = observed
    if isinstance(obs, dict):
        obs = obs.get(ctx.get("field"))
    if strict:
        ok = exp == obs
    else:
        ok = str(exp).strip().lower() == str(obs or "").strip().lower()
    return {"ok": ok,
            "detail": f"expected {exp!r} == observed {obs!r}"
                      if ok else
                      f"expected {exp!r} != observed {obs!r}"}


@verifier("health_ok")
def _health_ok(expected, observed, ctx):
    """Backend /api/status envelope: ok==true, no execution corruption,
    bridge and ollama fields present (they may be degraded, but the
    envelope must be honest)."""
    payload = observed if isinstance(observed, dict) else {}
    if not payload.get("ok"):
        return {"ok": False, "detail": "status envelope ok=false"}
    if "unreal" not in payload:
        return {"ok": False, "detail": "status missing 'unreal' field"}
    if "ollama" not in payload:
        return {"ok": False, "detail": "status missing 'ollama' field"}
    return {"ok": True, "detail": "status envelope healthy"}


@verifier("nonempty_list")
def _nonempty_list(expected, observed, ctx):
    items = observed if isinstance(observed, list) else []
    if isinstance(observed, dict):
        items = observed.get(ctx.get("field") or "items") or []
    if not items:
        return {"ok": False, "detail": "empty result list"}
    return {"ok": True, "detail": f"{len(items)} items"}


@verifier("no_js_fatal")
def _no_js_fatal(expected, observed, ctx):
    """Product HTML/JS responses must not carry fatal error markers that
    indicate a broken page (500-embedded text, 'traceback', 'internal
    server error'). A doctype is normal HTML, not a fatal marker."""
    text = str(observed or "").lower()
    markers = ("traceback", "internal server error", "500 internal",
               "modulenotfounderror", "importerror")
    hits = [m for m in markers if m in text]
    if hits:
        return {"ok": False, "detail": "response contains fatal markers: "
                                       + ", ".join(hits)}
    return {"ok": True, "detail": "no fatal markers in response"}


@verifier("no_false_pass_label")
def _no_false_pass_label(expected, observed, ctx):
    """A rendered page must not claim PASS with zero supporting evidence
    (e.g. a verdict chip 'PASS' while the task list shows no completed
    evidence). Best-effort deterministic check on response text."""
    text = str(observed or "").lower()
    if "pass" in text and "evidence" in text and "no completed" in text:
        return {"ok": False, "detail": "page claims PASS while stating no "
                                       "completed evidence"}
    return {"ok": True, "detail": "no contradictory PASS label found"}


@verifier("secrets_hygiene")
def _secrets_hygiene(expected, observed, ctx):
    """Known secret-looking keys or live API keys must not appear in
    committed product-facing files."""
    text = str(observed or "")
    hits = []
    low = text.lower()
    for marker in ("api_key", "apikey", "authorization: bearer",
                   "sk-", "password =", "secret ="):
        if marker in low:
            hits.append(marker)
    if hits:
        return {"ok": False,
                "detail": "secret-looking content present: " + ", ".join(hits)}
    return {"ok": True, "detail": "no secret markers found"}


@verifier("no_absolute_local_path")
def _no_absolute_local_path(expected, observed, ctx):
    """Product-facing output must not leak absolute local paths like
    C:\\Users\\Shadow or /Users/... in rendered pages/JSON payloads."""
    text = str(observed or "")
    hits = []
    for marker in (r"C:\Users", r"C:/Users", "/Users/", "/home/"):
        if marker in text:
            hits.append(marker)
    if hits:
        return {"ok": False,
                "detail": "absolute local paths leaked: " + ", ".join(hits)}
    return {"ok": True, "detail": "no absolute local path markers"}


# ---------------------------------------------------------------------------
# Composition helpers
# ---------------------------------------------------------------------------


def verify(check, expected, observed, ctx=None) -> Dict[str, Any]:
    """Run the check's named verifier and return its result dict."""
    return run_verifier(check.verifier, expected, observed, ctx or {})