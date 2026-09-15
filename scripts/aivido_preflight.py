#!/usr/bin/env python
"""AIVIDO preflight: prove the automation stack is alive BEFORE a run starts.

Checks (each reports a PASS/WARN/FAIL line and a machine-readable JSON blob):
  1. Unreal bridge port (default 127.0.0.1:6766) accepts connections and pings.
  2. Backend API (default 127.0.0.1:8765/api/status) responds.
  3. Ollama text generation answers within a bounded time (default 120s).
  4. Vision runner probe: a SHORT bounded request through the same Ollama
     runtime that serves the vision model. Slow-but-alive runners are
     reported as degraded (WARN), not fatal — deterministic pixel metrics
     take over and the LLM vision gate is reported honestly as unavailable.
  5. llama-server wedge detector: any llama-server process burning > WEDGE_CPU%
     CPU for minutes is killed once (self-heal), then the text check retries.
  6. Ollama serve self-heal: if nothing answers on 11434 but a binary exists,
     it is launched once (bounded wait), then checks re-run.

Exit codes:
  0 = all critical checks pass (text WARN still allowed)
  1 = at least one critical check failed (do not start the run)
  2 = usage error

Usage:
  python scripts/aivido_preflight.py            # full check, JSON to stdout
  python scripts/aivido_preflight.py --no-heal  # detect wedge but never kill
  python scripts/aivido_preflight.py --json-out /path/out.json
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

BRIDGE_HOST = os.getenv("AIVIDO_BRIDGE_HOST", "127.0.0.1")
BRIDGE_PORT = int(os.getenv("AIVIDO_BRIDGE_PORT", "6766"))
BACKEND_URL = os.getenv("AIVIDO_BACKEND_URL", "http://127.0.0.1:8765/api/status")
OLLAMA_BASE = os.getenv("AIVIDO_OLLAMA_URL", "http://127.0.0.1:11434")
TEXT_MODEL = os.getenv("AIVIDO_TEXT_MODEL", "qwen2.5-coder:14b")
VISION_MODEL = os.getenv("AIVIDO_VISION_MODEL", "qwen3-vl:8b-instruct")
TEXT_TIMEOUT = int(os.getenv("AIVIDO_TEXT_TIMEOUT", "120"))
VISION_PROBE_TIMEOUT = int(os.getenv("AIVIDO_VISION_PROBE_TIMEOUT", "20"))
VISION_DEGRADED_S = float(os.getenv("AIVIDO_VISION_DEGRADED_S", "10"))
WEDGE_CPU = float(os.getenv("AIVIDO_WEDGE_CPU", "150.0"))
WEDGE_IDLE_MIN = int(os.getenv("AIVIDO_WEDGE_IDLE_MIN", "3"))
OLLAMA_WARMUP_S = int(os.getenv("AIVIDO_OLLAMA_WARMUP_S", "90"))

HEAL = "--no-heal" not in sys.argv


def check_bridge() -> dict:
    t0 = time.time()
    try:
        s = socket.create_connection((BRIDGE_HOST, BRIDGE_PORT), timeout=5)
        s.sendall(b'{"type":"ping"}\n')
        buf = b""
        while not buf.endswith(b"\n") and time.time() - t0 < 20:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        s.close()
        data = json.loads(buf.decode().strip())
        ok = bool(data.get("ok")) and "UNREAL_BRIDGE_READY" in str(data.get("message", ""))
        return {"check": "bridge", "ok": ok, "engine": data.get("engine"),
                "latency_s": round(time.time() - t0, 2)}
    except Exception as exc:
        return {"check": "bridge", "ok": False, "error": f"{type(exc).__name__}: {exc}"}


def check_backend() -> dict:
    t0 = time.time()
    try:
        with urllib.request.urlopen(BACKEND_URL, timeout=10) as r:
            data = json.load(r)
        unreal = data.get("unreal", {}) if isinstance(data, dict) else {}
        return {"check": "backend", "ok": bool(data.get("ok")),
                "version": data.get("version"),
                "unreal_ok": bool(unreal.get("ok")),
                "latency_s": round(time.time() - t0, 2)}
    except Exception as exc:
        return {"check": "backend", "ok": False, "error": f"{type(exc).__name__}: {exc}"}


def llama_server_procs() -> list[dict]:
    procs = []
    try:
        out = subprocess.run(
            ["ps", "aux"], capture_output=True, text=True, timeout=15,
        )
        for line in out.stdout.splitlines():
            if "llama-server" in line and "grep" not in line:
                parts = line.split()
                if len(parts) > 10:
                    procs.append({
                        "pid": int(parts[1]),
                        "cpu": float(parts[2]),
                        "minutes": float(parts[9]),
                    })
    except Exception:
        pass
    return procs


def heal_wedged_runners() -> list[dict]:
    """Kill llama-server processes burning huge CPU with no work to do.

    The wedge signature observed on this machine: a llama-server at 400-600%
    CPU for hours while /api/ps lists no models, and every generation request
    (even 5 tokens) takes minutes. A fresh load fixes it.
    """
    healed = []
    for p in llama_server_procs():
        wedged = p["cpu"] > WEDGE_CPU and p["minutes"] > WEDGE_IDLE_MIN
        if wedged and HEAL:
            try:
                subprocess.run(["kill", str(p["pid"])], timeout=10)
                time.sleep(3)
                still = subprocess.run(
                    ["ps", "-p", str(p["pid"])], capture_output=True, timeout=10,
                )
                if still.returncode == 0:
                    subprocess.run(["kill", "-9", str(p["pid"])], timeout=10)
                healed.append({"pid": p["pid"], "action": "killed",
                               "cpu": p["cpu"], "minutes": p["minutes"]})
            except Exception as exc:
                healed.append({"pid": p["pid"], "action": "kill_failed",
                               "error": str(exc)})
        elif wedged:
            healed.append({"pid": p["pid"], "action": "wedged_not_healed",
                           "cpu": p["cpu"], "minutes": p["minutes"]})
    return healed


def _ollama_post(path: str, body: dict, timeout: float) -> dict:
    import urllib.error
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        OLLAMA_BASE + path, data=data,
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        payload = json.load(r)
    return {"payload": payload, "latency_s": round(time.time() - t0, 1)}


def try_start_ollama() -> dict:
    """One bounded attempt to start 'ollama serve' when nothing is listening."""
    if HEAL is False:
        return {"action": "skipped_no_heal"}
    binary = shutil.which("ollama")
    if not binary:
        return {"action": "binary_not_found"}
    log = os.path.expanduser("~/Desktop/AIVIDO_MAC_LOGS/ollama_serve_recovery.log")
    try:
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "a") as fh:
            subprocess.Popen(
                [binary, "serve"], stdout=fh, stderr=subprocess.STDOUT,
                start_new_session=True)
    except Exception as exc:
        return {"action": "start_failed", "error": str(exc)[:120]}
    deadline = time.time() + OLLAMA_WARMUP_S
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(OLLAMA_BASE + "/api/tags", timeout=3):
                return {"action": "started", "waited_s": round(time.time() - (deadline - OLLAMA_WARMUP_S), 1)}
        except Exception:
            time.sleep(2)
    return {"action": "started_but_not_ready"}


def check_text_gen(healed: list[dict] | None = None) -> dict:
    body = {
        "model": TEXT_MODEL,
        "prompt": "Reply with the single word READY.",
        "stream": False,
        "options": {"num_predict": 8},
    }
    t0 = time.time()
    try:
        out = _ollama_post("/api/generate", body, TEXT_TIMEOUT)
        text = str(out["payload"].get("response", "")).strip()
        ok = "READY" in text.upper()
        result = {"check": "text_gen", "ok": ok, "model": TEXT_MODEL,
                  "reply": text[:60], "latency_s": out["latency_s"]}
        if healed:
            result["healed"] = healed
        return result
    except Exception as exc:
        return {"check": "text_gen", "ok": False, "model": TEXT_MODEL,
                "error": f"{type(exc).__name__}: {exc}",
                "latency_s": round(time.time() - t0, 1)}


def check_vision_runner() -> dict:
    """Bounded probe of the vision runner.

    - ok            : vision gate can be trusted this run
    - degraded      : runtime alive but too slow for a vision gate; downstream
                      must fall back to deterministic metrics and say so
    - unavailable   : runtime down (after one heal attempt)
    Never blocks the run: only the CRITICAL checks do.
    """
    body = {
        "model": VISION_MODEL,
        "prompt": "Reply with the single word READY.",
        "stream": False,
        "options": {"num_predict": 4},
    }
    t0 = time.time()
    try:
        out = _ollama_post("/api/generate", body, VISION_PROBE_TIMEOUT)
        text = str(out["payload"].get("response", "")).strip()
        latency = out["latency_s"]
        if text:
            if latency <= VISION_DEGRADED_S:
                return {"check": "vision_runner", "ok": True, "status": "ok",
                        "model": VISION_MODEL, "latency_s": latency}
            return {"check": "vision_runner", "ok": True, "status": "degraded",
                    "model": VISION_MODEL, "latency_s": latency,
                    "note": (f"vision runtime slow ({latency}s > {VISION_DEGRADED_S}s budget); "
                             "evidence falls back to deterministic pixel metrics and the "
                             "LLM vision gate is reported as unavailable")}
        return {"check": "vision_runner", "ok": False, "status": "unavailable",
                "model": VISION_MODEL, "latency_s": latency, "error": "empty reply"}
    except Exception as exc:
        return {"check": "vision_runner", "ok": False, "status": "unavailable",
                "model": VISION_MODEL, "latency_s": round(time.time() - t0, 1),
                "error": f"{type(exc).__name__}: {exc}"[:160]}


def main() -> int:
    results: list[dict] = []
    results.append(check_bridge())
    results.append(check_backend())

    text = check_text_gen()
    if not text.get("ok"):
        # Wedge heal first (existing signature), then cold-start recovery.
        healed = heal_wedged_runners()
        if not healed:
            start = try_start_ollama()
            text["ollama_start_attempt"] = start
        if healed:
            time.sleep(2)
            text = check_text_gen(healed)
        else:
            text = check_text_gen()
    results.append(text)

    vision = check_vision_runner()
    if vision.get("status") == "unavailable":
        healed = heal_wedged_runners()
        if healed:
            time.sleep(2)
            vision = check_vision_runner()
            vision["healed"] = healed
    results.append(vision)

    critical = (results[0], results[1], results[2])  # bridge, backend, text_gen
    ok_all = all(r.get("ok") for r in critical)
    print(json.dumps({
        "verdict": "PASS" if ok_all else "FAIL",
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "vision_gate": vision.get("status"),
        "results": results,
    }, indent=2))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
