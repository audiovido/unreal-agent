#!/usr/bin/env python3
"""LIVE Unreal graduation probe: viewport capture / proof (Phase 14).

Read-only apart from writing one PNG into the project Saved/UnrealAgent dir.
Verifies a fresh, valid PNG that reflects the current project/world, plus the
web proof endpoint behavior on the running backend on 8765."""
from __future__ import annotations

import json
import os
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests

from tools.unreal.unreal_bridge import UnrealBridge

bridge = UnrealBridge(timeout=90)
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(("PASS" if ok else "FAIL") + f" {name}" + (f" | {detail}" if detail else ""), flush=True)


def payload(result):
    if isinstance(result, dict):
        inner = result.get("result")
        return inner if isinstance(inner, dict) else result
    return {}


def is_png(path):
    try:
        with open(path, "rb") as f:
            head = f.read(24)
        return head[:8] == b"\x89PNG\r\n\x1a\n" and len(head) == 24
    except Exception:
        return False


try:
    ident = payload(bridge.get_project_identity())
    project_name = ident.get("project_name") or ""
    world = payload(bridge.get_current_level())
    world_name = world.get("world_name") or ""

    before = time.time()
    result = bridge.capture_unreal_viewport()
    p = payload(result)
    check("capture_unreal_viewport ok", p.get("ok") is True, json.dumps(p)[:250])
    path = p.get("path")
    check("capture returns path", bool(path), str(path))
    check("capture file exists", bool(path and os.path.isfile(path)), str(path))
    check("capture file non-empty", bool(path and os.path.getsize(path) > 0), str(os.path.getsize(path)) if path else "0")
    check("valid PNG signature", bool(path and is_png(path)), str(path))
    # Not stale: file mtime within the last 2 minutes
    fresh = bool(path and (time.time() - os.path.getmtime(path)) < 120)
    check("capture is fresh (mtime < 2 min)", fresh, str(path))
    # Project-scoped: the capture path lives under the CURRENT project's Saved
    # dir, so a capture can never be stale from another project.
    project_scoped = bool(path and project_name and (project_name in str(path).replace("\\", "/")))
    check("capture reflects current project (path-scoped)", project_scoped, str(path))

    # proof endpoints on the running backend
    for url in ("http://127.0.0.1:8765/api/proof/latest", "http://127.0.0.1:8765/api/status"):
        try:
            r = requests.get(url, timeout=20)
            check(f"GET {url.split('8765')[1]} http {r.status_code}", r.status_code < 500, str(r.status_code))
        except Exception as exc:
            check(f"GET {url}", False, str(exc))
finally:
    pass

failed = [name for name, ok in results if not ok]
print("CAPTURE_PROOF_LIVE:", "PASS" if not failed else f"FAIL ({len(failed)})", flush=True)
sys.exit(0 if not failed else 1)