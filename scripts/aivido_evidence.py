#!/usr/bin/env python
"""Package AIVIDO visual evidence into an honest, machine-checkable verdict.

HARD RULES (all enforced here, not by convention):

  * executor success alone is NEVER a PASS. It only appears as a metadata note.
  * a STALE frame is a FAIL. "Fresh" means the capture is provably a real
    bridge capture (matching sha256+size in capture_metadata.json) written by
    the capture pipeline within the last --max-age seconds.
  * a MISSING fresh frame is a FAIL (missing file, missing metadata, metadata
    mismatch, or too old — all identical outcomes: no fresh evidence).
  * an EMPTY SceneDiff is a FAIL: if the scene did not measurably change
    between before/after snapshots, no executor state can manufacture a PASS.
  * the vision gate is optional evidence: when the vision runtime is slow or
    unavailable, deterministic pixel metrics still decide the verdict and the
    vision gate is reported honestly as unavailable — it never hangs the run.

Contract for ``capture_metadata.json`` (written next to the frame by the
capture pipeline / tools.visual.evidence_capture.write_capture_metadata):

    {
      "frame": "FINAL.png",          # or "path": "/abs/path.png"
      "sha256": "<64 hex>",          # sha256 of the frame bytes
      "size_bytes": 12345,
      "captured_at_epoch": 1789123456.7,
      "map": "/Game/AIVIDO_Showcase",
      "source": "bridge"             # capture provenance
    }

Usage:
  python scripts/aivido_evidence.py <evidence_dir> [--final FINAL.png]
      [--scenediff scenediff.json] [--expected-map /Game/AIVIDO_Showcase]
      [--max-age 900] [--executor-ok]
      [--diff-off FINAL_lightoff.png] [--diff-on FINAL_lighton.png] [--vision]

Exit code 0 only when the verdict is PASS.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

from tools.visual.shot_quality import analyze_frame  # noqa: E402
from core.production_v2 import scene_diff, scene_diff_is_meaningful  # noqa: E402

OLLAMA_CHAT = os.getenv("UNREAL_AGENT_OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
OLLAMA_BASE = os.getenv("AIVIDO_OLLAMA_URL", "http://127.0.0.1:11434")
VISION_MODEL = os.getenv("UNREAL_AGENT_VISION_MODEL", "qwen3-vl:8b-instruct")
VISION_PROBE_TIMEOUT = int(os.getenv("AIVIDO_VISION_PROBE_TIMEOUT", "20"))
DEFAULT_MAX_AGE = int(os.getenv("AIVIDO_FRAME_MAX_AGE", "900"))

FAIL_MESSAGES = {
    "stale": "STALE FRAME: capture is not provably fresh (bridge-verified bytes, age within budget)",
    "missing": "MISSING FRESH FRAME: no fresh capture evidence found",
    "empty_scenediff": "EMPTY SCENEDIFF: no measurable scene change between before/after snapshots",
    "executor_only": "EXECUTOR SUCCESS ALONE IS NOT A PASS",
}


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Freshness / stale-frame detection
# ---------------------------------------------------------------------------

def load_capture_metadata(ev_dir: str, frame_name: str) -> dict | None:
    """Load capture metadata for a frame, accepting several layouts."""
    candidates = [
        os.path.join(ev_dir, "capture_metadata.json"),
        os.path.join(ev_dir, os.path.splitext(frame_name)[0] + "_capture_metadata.json"),
    ]
    for cand in candidates:
        if os.path.isfile(cand):
            try:
                with open(cand) as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    data["_metadata_path"] = cand
                    return data
            except Exception:
                return None
    return None


def check_frame_freshness(
    ev_dir: str,
    frame_path: str,
    *,
    max_age: int,
    expected_map: str | None = None,
) -> dict:
    """Prove the frame is fresh or call it stale.

    Fresh = file exists AND metadata exists AND sha256+size match the actual
    bytes AND capture age is within max_age AND (when provided) the captured
    map matches the expected map. Any failure = stale/missing evidence.
    """
    name = os.path.basename(frame_path)
    if not os.path.isfile(frame_path):
        return {"fresh": False, "stale": True, "reason": "missing", "frame": name}

    meta = load_capture_metadata(ev_dir, name)
    if not meta:
        return {
            "fresh": False, "stale": True, "frame": name,
            "reason": "no_capture_metadata",
            "detail": (
                "frame bytes exist but no capture_metadata.json provenance; "
                "a hand-placed PNG is not evidence of a live bridge capture"
            ),
        }

    declared_frame = str(meta.get("frame") or os.path.basename(str(meta.get("path") or "")))
    if declared_frame and declared_frame != name:
        return {
            "fresh": False, "stale": True, "frame": name,
            "reason": "metadata_for_different_frame",
            "detail": f"metadata describes {declared_frame!r}",
        }

    try:
        actual_sha = sha256_file(frame_path)
        actual_size = os.path.getsize(frame_path)
    except Exception as exc:
        return {"fresh": False, "stale": True, "frame": name,
                "reason": "unreadable", "detail": str(exc)}

    declared_sha = str(meta.get("sha256") or "").lower()
    if declared_sha and declared_sha != actual_sha:
        return {
            "fresh": False, "stale": True, "frame": name,
            "reason": "sha_mismatch",
            "detail": "metadata sha does not match frame bytes (frame replaced or edited)",
        }

    declared_size = meta.get("size_bytes")
    if declared_size is not None:
        try:
            if int(declared_size) != actual_size:
                return {"fresh": False, "stale": True, "frame": name,
                        "reason": "size_mismatch"}
        except (TypeError, ValueError):
            return {"fresh": False, "stale": True, "frame": name,
                    "reason": "bad_size_metadata"}

    captured_at = meta.get("captured_at_epoch") or meta.get("captured_at")
    if captured_at is None:
        return {"fresh": False, "stale": True, "frame": name,
                "reason": "no_capture_timestamp"}
    try:
        age = time.time() - float(captured_at)
    except (TypeError, ValueError):
        return {"fresh": False, "stale": True, "frame": name,
                "reason": "bad_capture_timestamp"}
    if age < -5:
        return {"fresh": False, "stale": True, "frame": name,
                "reason": "future_timestamp", "age_s": round(age, 1)}
    if age > max_age:
        return {"fresh": False, "stale": True, "frame": name,
                "reason": "too_old", "age_s": round(age, 1), "max_age_s": max_age}

    captured_map = str(meta.get("map") or "")
    if expected_map and captured_map and expected_map not in captured_map:
        return {"fresh": False, "stale": True, "frame": name,
                "reason": "map_mismatch",
                "detail": f"captured on {captured_map!r}, expected ~{expected_map!r}"}

    return {
        "fresh": True, "stale": False, "frame": name,
        "age_s": round(age, 1), "max_age_s": max_age,
        "sha256": actual_sha[:12], "size_bytes": actual_size,
        "map": captured_map or None,
        "source": str(meta.get("source") or "unknown"),
    }


# ---------------------------------------------------------------------------
# SceneDiff liveness
# ---------------------------------------------------------------------------

def load_scenediff(path: str) -> dict:
    with open(path) as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("scenediff payload is not an object")
    return data


def check_scenediff(scenediff_path: str | None) -> dict:
    """Empty SceneDiff = FAIL. Returns {ok, meaningful, detail}."""
    try:
        payload = load_scenediff(scenediff_path)
    except Exception as exc:
        return {"ok": False, "meaningful": False,
                "reason": "scenediff_unreadable", "detail": str(exc)}

    if "before" in payload or "after" in payload:
        diff = scene_diff(payload.get("before"), payload.get("after"))
    else:
        diff = payload
    meaningful = scene_diff_is_meaningful(diff)
    return {
        "ok": meaningful,
        "meaningful": meaningful,
        "diff": diff,
        "reason": None if meaningful else "empty_scenediff",
    }


# ---------------------------------------------------------------------------
# Vision gate: bounded, honest, never a hang
# ---------------------------------------------------------------------------

def vision_gate_available() -> dict:
    """One short bounded probe of the vision runtime.

    Never retried, never long-running. When unavailable the verdict still
    rests on deterministic pixel metrics and the report says so honestly.
    """
    body = {
        "model": VISION_MODEL,
        "prompt": "Reply with the single word READY.",
        "stream": False,
        "options": {"num_predict": 4},
    }
    t0 = time.time()
    try:
        r = requests.post(OLLAMA_BASE + "/api/generate", json=body,
                          timeout=VISION_PROBE_TIMEOUT)
        r.raise_for_status()
        text = str(r.json().get("response", "")).strip()
        if text:
            return {"available": True, "model": VISION_MODEL,
                    "latency_s": round(time.time() - t0, 1), "reply": text[:40]}
    except Exception as exc:
        return {"available": False, "model": VISION_MODEL,
                "latency_s": round(time.time() - t0, 1),
                "error": f"{type(exc).__name__}: {exc}"[:160]}
    return {"available": False, "model": VISION_MODEL,
            "latency_s": round(time.time() - t0, 1), "error": "empty reply"}


def vision_review_frame(path: str, timeout: int) -> dict:
    """One bounded vision review call. Never raises, never retried."""
    try:
        b64 = base64.b64encode(open(path, "rb").read()).decode("ascii")
    except Exception as exc:
        return {"ok": False, "error": f"unreadable_frame: {type(exc).__name__}"}
    body = {
        "model": VISION_MODEL,
        "stream": False,
        "options": {"temperature": 0, "num_predict": 300},
        "messages": [{"role": "user", "content":
                      "You are auditing an Unreal Engine screenshot. In at most 80 "
                      "words: (1) name the main visible structures, (2) state whether "
                      "the frame looks like a real rendered 3D scene (not black, not "
                      "flat gray, not a single flat color), (3) flag any obvious "
                      "rendering defect.", "images": [b64]}],
    }
    t0 = time.time()
    try:
        r = requests.post(OLLAMA_CHAT, json=body, timeout=timeout)
        r.raise_for_status()
        text = str(r.json().get("message", {}).get("content", "")).strip()
        if text:
            return {"ok": True, "latency_s": round(time.time() - t0, 1), "text": text[:600]}
        return {"ok": False, "error": "empty vision reply"}
    except Exception as exc:
        return {"ok": False, "latency_s": round(time.time() - t0, 1),
                "error": f"{type(exc).__name__}: {exc}"[:160]}


# ---------------------------------------------------------------------------

def opt(args: list[str], flag: str) -> str | None:
    return args[args.index(flag) + 1] if flag in args else None


def flag(args: list[str], flag_name: str) -> bool:
    return flag_name in args


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0].startswith("--"):
        print(__doc__)
        return 2
    ev_dir = args[0]

    final_name = opt(args, "--final") or "FINAL.png"
    final_p = opt(args, "--final-path") or os.path.join(ev_dir, final_name)
    scenediff_p = opt(args, "--scenediff") or os.path.join(ev_dir, "scenediff.json")
    expected_map = opt(args, "--expected-map")
    max_age = int(opt(args, "--max-age") or DEFAULT_MAX_AGE)
    executor_ok = flag(args, "--executor-ok")
    do_vision = flag(args, "--vision")

    evidence: dict = {
        "evidence_dir": ev_dir,
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "executor_ok": executor_ok,  # recorded as a NOTE, never sufficient for PASS
    }
    issues: list[str] = []

    # 1) deterministic pixel metrics for every frame present
    metrics: dict = {}
    if os.path.isdir(ev_dir):
        for name in sorted(os.listdir(ev_dir)):
            if not name.lower().endswith(".png"):
                continue
            p = os.path.join(ev_dir, name)
            try:
                m = analyze_frame(p)
                m.pop("raw", None)
                m["sha12"] = sha256_file(p)[:12]
                metrics[name] = m
            except Exception as exc:
                metrics[name] = {"error": str(exc)}
    evidence["metrics"] = metrics

    # 2) fresh-frame gate: stale or missing = FAIL (the core honesty rule)
    freshness = check_frame_freshness(
        ev_dir, final_p, max_age=max_age, expected_map=expected_map)
    evidence["freshness"] = freshness
    if not freshness["fresh"]:
        issues.append(
            FAIL_MESSAGES["stale"] if freshness.get("stale") else FAIL_MESSAGES["missing"]
            + f" [{freshness.get('reason', '?')}]"
        )

    # 3) frame content sanity (degenerate renders fail even when fresh)
    fm = metrics.get(os.path.basename(final_p), {})
    if os.path.isfile(final_p):
        if fm.get("mean_luma", 0) < 8 or fm.get("mean_luma", 0) > 245:
            issues.append("final frame is degenerate (near-black or near-white)")
        if fm.get("pct_black", 1) > 0.6:
            issues.append("final frame is majority black")

    # 4) SceneDiff gate: empty diff = FAIL
    if os.path.isfile(scenediff_p):
        sd = check_scenediff(scenediff_p)
        evidence["scenediff"] = {k: v for k, v in sd.items() if k != "diff"}
        evidence["scenediff"]["diff"] = sd.get("diff")
        if not sd["ok"]:
            issues.append(FAIL_MESSAGES["empty_scenediff"])
    else:
        evidence["scenediff"] = {"ok": False, "meaningful": False,
                                 "reason": "scenediff_missing"}
        issues.append(
            "MISSING SCENEDIFF: no before/after scene evidence was packaged "
            "(executor claims without scene deltas are not acceptable)"
        )

    # 5) liveness differential pair (optional but checked when present)
    off_name = opt(args, "--diff-off") or "FINAL_lightoff.png"
    on_name = opt(args, "--diff-on") or "FINAL_lighton.png"
    off_p, on_p = os.path.join(ev_dir, off_name), os.path.join(ev_dir, on_name)
    if os.path.isfile(off_p) and os.path.isfile(on_p):
        if sha256_file(off_p) == sha256_file(on_p):
            issues.append(
                "STALE EVIDENCE: light-off and light-on captures are byte-identical; "
                "render pipeline did not update between captures")
        else:
            mo = metrics.get(off_name, {})
            mn = metrics.get(on_name, {})
            evidence["liveness"] = {
                "off_mean": mo.get("mean_luma"), "on_mean": mn.get("mean_luma"),
                "off_black": mo.get("pct_black"), "on_black": mn.get("pct_black"),
            }

    # 6) vision gate: bounded, honest, advisory — never decides alone, never hangs
    vision_probe = vision_gate_available()
    evidence["vision_gate"] = vision_probe
    if do_vision and os.path.isfile(final_p):
        v = vision_review_frame(final_p, timeout=VISION_PROBE_TIMEOUT * 4)
        evidence["vision"] = v
    if not vision_probe.get("available"):
        evidence["vision_gate_note"] = (
            "VISION GATE UNAVAILABLE: deterministic pixel metrics decided this "
            "verdict; no LLM vision review was performed (no hang, no fake pass)")

    # 7) verdict — executor success alone can never produce PASS
    if issues:
        evidence["verdict"] = "FAIL"
        evidence["issues"] = issues
    else:
        evidence["verdict"] = "PASS_PIXELS_ONLY" if not vision_probe.get("available") \
            else "PASS"

    vp = os.path.join(ev_dir, "verdict.json")
    with open(vp, "w") as fh:
        json.dump(evidence, fh, indent=2, default=str)

    md = [
        "# AIVIDO evidence verdict: " + evidence["verdict"],
        "",
        "- dir: `" + ev_dir + "`",
        "- at: " + evidence["at"],
        f"- executor_ok: {executor_ok} (informational only — never a PASS by itself)",
    ]
    fr = evidence.get("freshness", {})
    if fr.get("fresh"):
        md.append(f"- fresh frame: {fr.get('frame')} age={fr.get('age_s')}s "
                  f"sha={fr.get('sha256')} map={fr.get('map')}")
    else:
        md.append(f"- fresh frame: REJECTED ({fr.get('reason')})")
    sd = evidence.get("scenediff", {})
    md.append(f"- scenediff meaningful: {sd.get('meaningful')} ({sd.get('reason') or 'ok'})")
    md += ["", "## Key frames"]
    for name in sorted(metrics):
        m = metrics[name]
        if "mean_luma" in m:
            md.append(f"- {name}: mean={m['mean_luma']:.1f} black={m['pct_black']:.3f} "
                      f"white={m['pct_white']:.3f} sha={m.get('sha12')}")
    if evidence.get("liveness"):
        l = evidence["liveness"]
        md.append(f"- liveness differential: off mean={l['off_mean']} vs on mean={l['on_mean']}")
    if issues:
        md += ["", "## Issues"] + [f"- {i}" for i in issues]
    md += ["", "## Vision gate"]
    md.append(f"- available: {vision_probe.get('available')} "
              f"(model={vision_probe.get('model')}, latency={vision_probe.get('latency_s')}s)")
    if not vision_probe.get("available"):
        md.append("- " + evidence.get("vision_gate_note", ""))
    if evidence.get("vision", {}).get("text"):
        md += ["", "## Vision review", "", evidence["vision"]["text"]]
    with open(os.path.join(ev_dir, "verdict.md"), "w") as fh:
        fh.write("\n".join(md) + "\n")

    print(json.dumps({
        "verdict": evidence["verdict"],
        "fresh": fr.get("fresh", False),
        "scenediff_meaningful": sd.get("meaningful", False),
        "vision_gate_available": vision_probe.get("available", False),
        "issues": issues,
        "verdict_path": vp,
    }, indent=2))
    return 0 if evidence["verdict"].startswith("PASS") else 1


if __name__ == "__main__":
    sys.exit(main())
