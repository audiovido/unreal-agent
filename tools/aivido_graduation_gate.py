#!/usr/bin/env python3
"""AIVIDO graduation gate — the one-click trust boundary.

Runs, in order:
  1. scripts/aivido_preflight.py  (backend/bridge/text/vision checks with
     automatic recovery of wedged Ollama runners)
  2. a READ-ONLY live Unreal probe through the bridge: verifies the editor is
     on the expected map with a healthy actor count. The probe only reads
     (EditorActorSubsystem + get_editor_world); it never mutates the scene.

Output: a machine-readable JSON verdict on stdout and --json-out. Exit code 0
only on PASS. The one-click command hard-fails on non-zero.

Usage:
  python tools/aivido_graduation_gate.py \
      --expected-map /Game/AIVIDO_Showcase --min-actors 20 \
      --json-out /path/gate.json
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import re
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 6766

# READ-ONLY probe: enumerates actors via the EditorActorSubsystem (the UE 5.7
# replacement for the deprecated get_all_level_actors, which can return
# duplicated handles whose transform reads raise). Never mutates the scene.
PROBE_CODE = '''
import unreal
world = unreal.EditorLevelLibrary.get_editor_world()
if world is None:
    __bridge_result__ = {"ok": False, "error": "editor_world_unavailable"}
else:
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
    names = []
    read_errors = []
    for a in actors:
        try:
            names.append(str(a.get_actor_label() or a.get_name()))
        except Exception as exc:
            read_errors.append(type(exc).__name__)
    __bridge_result__ = {
        "ok": True,
        "map": str(world.get_path_name() or ""),
        "actor_count": len(names),
        "read_errors": read_errors,
        "labels": sorted(names),
    }
'''


def load_preflight():
    path = ROOT / "scripts" / "aivido_preflight.py"
    spec = importlib.util.spec_from_file_location("aivido_preflight", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_preflight() -> dict:
    preflight = load_preflight()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = preflight.main()
    try:
        report = json.loads(buf.getvalue())
    except Exception:
        report = {"verdict": "FAIL", "parse_error": True, "raw": buf.getvalue()[:400]}
    report["exit_code"] = rc
    return report


def probe_live_scene(timeout: float = 30.0) -> dict:
    """Read-only live scene query through the bridge. Never mutates."""
    t0 = time.time()
    try:
        s = socket.create_connection((BRIDGE_HOST, BRIDGE_PORT), timeout=10)
        s.sendall(json.dumps({"type": "python", "code": PROBE_CODE}).encode() + b"\n")
        s.settimeout(timeout)
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        s.close()
        data = json.loads(buf.decode().strip())
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                "latency_s": round(time.time() - t0, 2)}

    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    if not data.get("ok") or not result.get("ok"):
        return {"ok": False,
                "error": str(data.get("error") or result.get("error") or "probe failed"),
                "latency_s": round(time.time() - t0, 2)}
    result["latency_s"] = round(time.time() - t0, 2)
    result["read_only"] = True
    return result


def audit_mission_labels(mission_text: str, live_labels: list) -> list:
    """Fail fast when the mission references actors that do not exist.

    Run 9 lost its first attempt to a stale brief: ``AIVIDO_CommandDais`` no
    longer existed (the real labels are ``AIVIDO_Dais_Tier1/Tier2``), so the
    executor burned its two attempts before the honest actor_not_found
    surfaced. Auditing every ``AIVIDO_*`` reference against the live label
    list converts that mid-execution stall into a pre-flight gate failure.

    A token is accepted when it IS a live label OR when it is a prefix of one
    ("the four AIVIDO_WorkerChairSeat actors" expands to real labels). Only
    tokens matching no live label and no live prefix are reported.
    """
    live = set(str(l) for l in (live_labels or []))
    if not live:
        return []
    # Map/asset paths (e.g. /Game/AIVIDO_Showcase) are not actor labels.
    text = re.sub(r"/Game/[A-Za-z0-9_]+", " ", str(mission_text))
    missing: list = []
    for token in sorted(set(re.findall(r"\bAIVIDO_[A-Za-z0-9_]+", text))):
        if token in live:
            continue
        if any(lb.startswith(token + "_") for lb in live):
            continue
        missing.append(token)
    return missing


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--expected-map", default="/Game/AIVIDO_Showcase")
    ap.add_argument("--min-actors", type=int, default=20)
    ap.add_argument("--mission-file", default="", help="Mission text to audit against live actor labels")
    ap.add_argument("--json-out", default="")
    a = ap.parse_args()

    reasons: list[str] = []
    report: dict = {
        "gate": "aivido_graduation_gate",
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "expected_map": a.expected_map,
        "min_actors": a.min_actors,
    }

    pre = run_preflight()
    report["preflight"] = {
        "verdict": pre.get("verdict"),
        "results": pre.get("results"),
        "vision_gate": pre.get("vision_gate"),
    }
    if pre.get("verdict") != "PASS":
        reasons.append("PREFLIGHT_FAILED")

    scene = probe_live_scene()
    report["live_scene"] = scene
    if not scene.get("ok"):
        reasons.append("LIVE_UNREAL_PROBE_FAILED")
    else:
        map_name = str(scene.get("map") or "")
        actor_count = scene.get("actor_count")
        report["map"] = map_name
        report["actor_count"] = actor_count
        if a.expected_map and a.expected_map not in map_name:
            reasons.append(f"WRONG_MAP:{map_name}")
        if not isinstance(actor_count, int) or actor_count < a.min_actors:
            reasons.append(f"ACTOR_COUNT_TOO_LOW:{actor_count}<{a.min_actors}")
        read_errors = scene.get("read_errors") or []
        if len(read_errors) > max(2, actor_count // 4 if actor_count else 2):
            reasons.append(f"SCENE_SNAPSHOT_PARTIAL:read_errors={len(read_errors)}")

    if a.mission_file:
        mission_path = Path(a.mission_file)
        if mission_path.is_file():
            missing = audit_mission_labels(
                mission_path.read_text(errors="replace"), scene.get("labels") or []
            )
            report["mission_label_audit"] = {"file": str(mission_path), "unknown": missing}
            for token in missing:
                reasons.append(f"MISSION_LABEL_UNKNOWN:{token}")
        else:
            reasons.append(f"MISSION_FILE_MISSING:{a.mission_file}")

    report["reasons"] = reasons
    report["verdict"] = "PASS" if not reasons else "FAIL"
    text = json.dumps(report, indent=2)
    print(text)
    if a.json_out:
        out = Path(a.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
    return 0 if report["verdict"] == "PASS" else 42


if __name__ == "__main__":
    raise SystemExit(main())
