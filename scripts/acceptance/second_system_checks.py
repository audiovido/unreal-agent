"""second_system_checks.py — python-side checks for the second-system
acceptance runner (scripts/acceptance/run_second_system_acceptance.ps1).

All checks are HERMETIC or strictly READ-ONLY against Unreal:

  env       -> JSON report: python version, import contract, port
               occupancy, bridge TCP state
  mission   -> ONE read-only mission against the live editor bridge:
               TCP reachability, ping, project identity, active map,
               UE version, and a viewport capture that writes ONLY the
               transient proof PNG (Saved/UnrealAgent/viewport_latest.png).
               Never spawns an actor, never changes the scene, never
               saves the level.
  evidence  -> verify /api/proof/latest serves a fresh, non-trivial PNG
               and (when --expected-path is given) that the served bytes
               are byte-identical to the freshly captured proof file.

Diagnostics are stable machine-readable codes so the PowerShell runner can
map them to failure explanations:

  PYTHON_MISSING, PYTHON_TOO_OLD, DEPENDENCY_MISSING, BRIDGE_UNAVAILABLE,
  UE_VERSION_MISMATCH, WRONG_PROJECT, WRONG_MAP, CAPTURE_FAILED,
  MISSION_FAILED, EVIDENCE_MISSING, EVIDENCE_INVALID, EVIDENCE_STALE
"""
from __future__ import annotations

import argparse
import hashlib
import json
import socket
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REQUIRED_PY = (3, 9)
SUPPORTED_UE_MAJOR = 5
IMPORT_CONTRACT = ("fastapi", "uvicorn", "PIL", "numpy", "pydantic",
                   "requests", "rich")
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MIN_EVIDENCE_BYTES = 1024


def _json_out(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2))


def _now() -> float:
    return time.time()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# env
# ---------------------------------------------------------------------------
def cmd_env(ports: List[int], bridge_host: str, bridge_port: int) -> int:
    report: Dict[str, Any] = {
        "python": {"version": None, "ok": False, "diag": None},
        "imports": {"ok": False, "missing": [], "diag": None},
        "ports": [],
        "bridge": {"host": bridge_host, "port": bridge_port,
                   "reachable": False, "diag": None},
    }
    v = sys.version_info
    report["python"]["version"] = f"{v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) >= REQUIRED_PY:
        report["python"]["ok"] = True
    else:
        report["python"]["diag"] = "PYTHON_TOO_OLD"

    missing = []
    for mod in IMPORT_CONTRACT:
        try:
            __import__(mod)
        except Exception as exc:
            missing.append({"module": mod, "error": type(exc).__name__})
    report["imports"]["missing"] = missing
    report["imports"]["ok"] = not missing
    if missing:
        report["imports"]["diag"] = "DEPENDENCY_MISSING"

    for port in ports:
        entry: Dict[str, Any] = {"port": port, "occupied": False,
                                 "who": None}
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    entry["occupied"] = True
        except Exception:
            pass
        report["ports"].append(entry)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2.0)
            if s.connect_ex((bridge_host, bridge_port)) == 0:
                report["bridge"]["reachable"] = True
    except Exception as exc:
        report["bridge"]["diag"] = f"BRIDGE_UNAVAILABLE:{type(exc).__name__}"

    _json_out(report)
    return 0


# ---------------------------------------------------------------------------
# bridge (READ-ONLY discovery: TCP + ping + identity + active map)
# ---------------------------------------------------------------------------
def cmd_bridge(bridge_host: str, bridge_port: int) -> int:
    report: Dict[str, Any] = {"tcp_ok": False, "ping_ok": False,
                              "engine": None, "project_name": None,
                              "project_path": None, "world_path": None,
                              "diag": None}
    try:
        from tools.unreal.unreal_bridge import UnrealBridge
    except Exception as exc:
        report["diag"] = f"DEPENDENCY_MISSING:{type(exc).__name__}"
        _json_out(report)
        return 1

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(5.0)
            report["tcp_ok"] = s.connect_ex((bridge_host, bridge_port)) == 0
    except Exception as exc:
        report["diag"] = f"BRIDGE_UNAVAILABLE:{type(exc).__name__}"
        _json_out(report)
        return 1
    if not report["tcp_ok"]:
        report["diag"] = "BRIDGE_UNAVAILABLE"
        _json_out(report)
        return 1

    bridge = UnrealBridge(host=bridge_host, port=bridge_port, timeout=20)
    try:
        resp = bridge.ping()
        payload = resp if isinstance(resp, dict) else {}
        report["ping_ok"] = bool(payload.get("ok") is True)
        report["engine"] = str(payload.get("engine") or "")
    except Exception as exc:
        report["diag"] = f"BRIDGE_UNAVAILABLE:{type(exc).__name__}"
        _json_out(report)
        return 1

    try:
        resp = bridge.get_project_identity()
        payload = resp.get("result") if isinstance(resp, dict) else None
        if isinstance(payload, dict) and payload.get("ok"):
            report["project_name"] = str(payload.get("project_name") or "")
            report["project_path"] = str(payload.get("project_path") or "")
    except Exception:
        pass

    try:
        resp = bridge.get_current_level()
        payload = resp.get("result") if isinstance(resp, dict) else None
        report["world_path"] = str((payload or {}).get("world_path") or "")
    except Exception:
        pass

    if not report["ping_ok"]:
        report["diag"] = "BRIDGE_UNAVAILABLE"
        _json_out(report)
        return 1
    _json_out(report)
    return 0


# ---------------------------------------------------------------------------
# mission (READ-ONLY)
# ---------------------------------------------------------------------------
def cmd_mission(bridge_host: str, bridge_port: int, expected_map: str,
                expected_project: str) -> int:
    steps: List[Dict[str, Any]] = []
    overall = "FAIL"
    diag = None
    mission_id = f"second_system_{time.strftime('%Y%m%d%H%M%S')}"
    evidence: Dict[str, Any] = {"path": None, "mtime": None, "size": 0,
                                "ok": False}

    def step(name: str, ok: bool, detail: str) -> None:
        steps.append({"name": name, "status": "PASS" if ok else "FAIL",
                      "detail": detail})

    try:
        from tools.unreal.unreal_bridge import UnrealBridge
    except Exception as exc:
        _json_out({"overall": "FAIL", "diag": "DEPENDENCY_MISSING",
                   "mission_id": mission_id,
                   "error": f"bridge client import failed: "
                            f"{type(exc).__name__}: {exc}",
                   "steps": steps, "evidence": evidence})
        return 1

    bridge = UnrealBridge(host=bridge_host, port=bridge_port, timeout=30)

    # Step 1: TCP reachability (never sends anything).
    reachable = False
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(5.0)
            reachable = s.connect_ex((bridge_host, bridge_port)) == 0
    except Exception as exc:
        diag = f"BRIDGE_UNAVAILABLE:{type(exc).__name__}"
    step("bridge_tcp", reachable,
         f"{bridge_host}:{bridge_port} reachable" if reachable
         else f"{bridge_host}:{bridge_port} not reachable")
    if not reachable and not diag:
        diag = "BRIDGE_UNAVAILABLE"

    # Step 2: read-only ping.
    if reachable:
        try:
            resp = bridge.ping()
            payload = resp if isinstance(resp, dict) else {}
            ping_ok = bool(payload.get("ok") is True)
            step("bridge_ping", ping_ok,
                 f"bridge answered ping engine="
                 f"{payload.get('engine') or '?'}")
            if not ping_ok and not diag:
                diag = "BRIDGE_UNAVAILABLE"
        except Exception as exc:
            diag = diag or f"BRIDGE_UNAVAILABLE:{type(exc).__name__}"
            step("bridge_ping", False,
                 f"ping failed: {type(exc).__name__}: {exc}")
    else:
        step("bridge_ping", False, "skipped: bridge unreachable")

    # Step 3: project identity (get_project_identity executes read-only
    # python in the editor; it never modifies the scene).
    project_name = ""
    ue_version = None
    if reachable:
        try:
            resp = bridge.get_project_identity()
            payload = resp.get("result") if isinstance(resp, dict) else None
            if isinstance(payload, dict) and payload.get("ok"):
                project_name = str(payload.get("project_name") or "")
                engine = str(payload.get("engine") or "")
                step("unreal_identity", True,
                     f"project={project_name} engine={engine}")
                nums = [int(t) for t in engine.replace(".", " ").split()
                        if t.isdigit()]
                if nums:
                    ue_version = nums[0]
            else:
                diag = diag or "WRONG_PROJECT"
                step("unreal_identity", False,
                     f"identity failed: {str(payload or resp)[:200]}")
        except Exception as exc:
            diag = diag or f"WRONG_PROJECT:{type(exc).__name__}"
            step("unreal_identity", False,
                 f"identity failed: {type(exc).__name__}: {exc}")
    else:
        step("unreal_identity", False, "skipped: bridge unreachable")

    # Step 4: expected project gate (when the operator pins one).
    if expected_project:
        match = (project_name or "").lower() == expected_project.lower()
        if match:
            step("project_match", True, f"project={project_name} "
                                        f"matches expected {expected_project}")
        else:
            diag = diag or "WRONG_PROJECT"
            step("project_match", False,
                 f"project={project_name or '(none)'} != expected "
                 f"{expected_project}")
    elif not project_name:
        diag = diag or "WRONG_PROJECT"

    # Step 5: active map gate (read-only get_current_level).
    world_path = ""
    if reachable:
        try:
            resp = bridge.get_current_level()
            payload = resp.get("result") if isinstance(resp, dict) else None
            world_path = str((payload or {}).get("world_path") or "")
            map_ok = world_path.startswith(expected_map)
            step("active_map", map_ok,
                 f"world_path={world_path or '(none)'} "
                 f"(expected {expected_map})")
            if not map_ok and not diag:
                diag = "WRONG_MAP"
        except Exception as exc:
            diag = diag or f"WRONG_MAP:{type(exc).__name__}"
            step("active_map", False,
                 f"map probe failed: {type(exc).__name__}: {exc}")
    else:
        step("active_map", False, "skipped: bridge unreachable")

    # Step 6: UE version gate (major >= 5 required).
    if reachable and ue_version is not None:
        if ue_version >= SUPPORTED_UE_MAJOR:
            step("ue_version", True, f"UE {ue_version} supported")
        else:
            diag = diag or f"UE_VERSION_MISMATCH:UE{ue_version}"
            step("ue_version", False,
                 f"UE {ue_version} < required UE {SUPPORTED_UE_MAJOR}")
    elif reachable and not ue_version:
        step("ue_version", True, "engine version not reported; assumed OK")

    # Step 7: read-only viewport capture. Writes ONLY the transient proof
    # PNG into Saved/UnrealAgent/; never touches the level, never saves.
    if reachable:
        try:
            resp = bridge.capture_unreal_viewport()
            payload = resp.get("result") if isinstance(resp, dict) else None
            cap_ok = bool(isinstance(payload, dict) and payload.get("ok"))
            path = str((payload or {}).get("path") or "")
            size = int((payload or {}).get("size") or 0)
            evidence = {"path": path or None, "size": size,
                        "mtime": None, "ok": cap_ok}
            if path:
                p = Path(path.replace("/", "\\"))
                if p.is_file():
                    evidence["mtime"] = round(p.stat().st_mtime, 3)
            step("viewport_capture", cap_ok,
                 f"capture {'ok' if cap_ok else 'failed'} "
                 f"path={path or '(none)'} size={size}")
            if not cap_ok and not diag:
                diag = "CAPTURE_FAILED"
        except Exception as exc:
            diag = diag or f"CAPTURE_FAILED:{type(exc).__name__}"
            step("viewport_capture", False,
                 f"capture failed: {type(exc).__name__}: {exc}")
    else:
        step("viewport_capture", False, "skipped: bridge unreachable")

    if all(s["status"] == "PASS" for s in steps):
        overall = "PASS"
        diag = None
    else:
        overall = "FAIL"
        diag = diag or "MISSION_FAILED"

    _json_out({"overall": overall, "diag": diag, "mission_id": mission_id,
               "steps": steps, "evidence": evidence})
    return 0 if overall == "PASS" else 1


# ---------------------------------------------------------------------------
# evidence
# ---------------------------------------------------------------------------
def cmd_evidence(base_url: str, max_age_minutes: float,
                 expected_path: str, min_mtime: float) -> int:
    url = base_url.rstrip("/") + "/api/proof/latest"
    served_sha = None
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = resp.read()
            last_modified = resp.headers.get("Last-Modified")
    except Exception as exc:
        _json_out({"overall": "FAIL", "diag": "EVIDENCE_MISSING",
                   "detail": f"{url} unreachable: {type(exc).__name__}: {exc}"})
        return 1

    served_sha = _sha256_bytes(data)
    if len(data) < MIN_EVIDENCE_BYTES:
        _json_out({"overall": "FAIL", "diag": "EVIDENCE_INVALID",
                   "detail": f"payload too small ({len(data)} bytes) "
                             f"to be real evidence"})
        return 1
    if not data.startswith(PNG_MAGIC):
        _json_out({"overall": "FAIL", "diag": "EVIDENCE_INVALID",
                   "detail": "payload is not a PNG"})
        return 1

    detail: Dict[str, Any] = {"bytes": len(data), "sha256": served_sha,
                              "age_minutes": None}

    # Preferred freshness source: the freshly captured proof file.
    if expected_path:
        p = Path(expected_path)
        if not p.is_file():
            _json_out({"overall": "FAIL", "diag": "EVIDENCE_MISSING",
                       "detail": f"captured proof missing on disk: {p}"})
            return 1
        mtime = p.stat().st_mtime
        file_sha = _sha256_bytes(p.read_bytes())
        detail["path"] = str(p)
        detail["mtime"] = round(mtime, 3)
        if mtime + 1.0 < min_mtime:
            _json_out({"overall": "FAIL", "diag": "EVIDENCE_STALE",
                       "detail": f"capture mtime {mtime} older than mission "
                                 f"start {min_mtime} (stale evidence)"})
            return 1
        if file_sha != served_sha:
            _json_out({"overall": "FAIL", "diag": "EVIDENCE_STALE",
                       "detail": "served evidence does not match the freshly "
                                 "captured proof (stale evidence)"})
            return 1
        detail["matches_capture"] = True
        detail["age_minutes"] = round((time.time() - mtime) / 60.0, 1)

    # Fallback freshness source: HTTP Last-Modified.
    if detail["age_minutes"] is None and last_modified:
        try:
            from email.utils import parsedate_to_datetime
            ts = parsedate_to_datetime(last_modified).timestamp()
            age_min = (time.time() - ts) / 60.0
            detail["age_minutes"] = round(age_min, 1)
            if age_min > max_age_minutes:
                _json_out({"overall": "FAIL", "diag": "EVIDENCE_STALE",
                           "detail": f"evidence is {age_min:.1f} min old "
                                     f"(limit {max_age_minutes})"})
                return 1
        except Exception:
            pass

    _json_out({"overall": "PASS", "diag": None, "detail": detail})
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["env", "bridge", "mission", "evidence"])
    ap.add_argument("--ports", default="8765",
                    help="comma-separated ports to probe")
    ap.add_argument("--bridge-host", default="127.0.0.1")
    ap.add_argument("--bridge-port", type=int, default=6766)
    ap.add_argument("--expected-map", default="/Game/Maps/AividoHQ")
    ap.add_argument("--expected-project", default="")
    ap.add_argument("--base-url", default="http://127.0.0.1:8765")
    ap.add_argument("--max-age-minutes", type=float, default=60.0)
    ap.add_argument("--expected-path", default="")
    ap.add_argument("--min-mtime", type=float, default=0.0)
    args = ap.parse_args()

    if args.command == "env":
        ports = [int(p) for p in args.ports.split(",") if p.strip()]
        return cmd_env(ports, args.bridge_host, args.bridge_port)
    if args.command == "bridge":
        return cmd_bridge(args.bridge_host, args.bridge_port)
    if args.command == "mission":
        return cmd_mission(args.bridge_host, args.bridge_port,
                           args.expected_map, args.expected_project)
    return cmd_evidence(args.base_url, args.max_age_minutes,
                        args.expected_path, args.min_mtime)


if __name__ == "__main__":
    sys.exit(main())