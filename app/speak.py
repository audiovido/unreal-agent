"""AvaLive chat auto-speak — fire-and-forget, single-flight MetaHuman speech.

After an assistant reply finishes, the UI calls POST /api/chat/speak. This runs
the PROVEN gate speak regression (frozen agent_line performance + SoundWave on
the existing MetaHuman in PIE) off the request thread. It never blocks the
reply, never piles up runs, and degrades truthfully when the AvaLive editor is
unreachable.

State ownership:
- _speak_state owns only active/pid (in-memory run bookkeeping).
- The run RESULT is owned by the gate subprocess's log file (_SPEAK_LOG) — the
  single source of truth; /api/chat/speak/status reads it live instead of
  keeping a second cached copy.
"""
from __future__ import annotations

import socket
import subprocess
import threading

from core.portable_paths import (BRIDGE_PORT, PACKAGE_ROOT, RUNTIME_DIR,
                                 python_executable)

_SPEAK_LOG = RUNTIME_DIR / "chat_speak_last.log"
_SPEAK_GATE = PACKAGE_ROOT / "scripts" / "avalive_gate.py"
_SPEAK_CONFIG = PACKAGE_ROOT / "scripts" / "avalive_gate.json"
_PYTHON = python_executable()
_ROOT = PACKAGE_ROOT
_AVALIVE_PORT = BRIDGE_PORT

_speak_lock = threading.Lock()
_speak_state = {"active": False, "pid": None}


def _speak_avalive_online() -> bool:
    """Cheap non-mutating liveness probe for the AvaLive bridge."""
    try:
        with socket.create_connection(("127.0.0.1", _AVALIVE_PORT), timeout=2):
            return True
    except Exception:
        return False


def _speak_last_result():
    """Latest structured result from the gate run log (single source of truth)."""
    try:
        if not _SPEAK_LOG.is_file():
            return None
        import json
        text = _SPEAK_LOG.read_text(encoding="utf-8", errors="replace")
        idx = text.find("{")
        if idx < 0:
            return None
        data = json.loads(text[idx:])
        result = (data.get("result") or {})
        status = result.get("status")
        # The gate fails safely at its identity pre-check whenever the editor on
        # the AvaLive port is not AvaLive (e.g. another project holds the shared
        # Unreal slot). Report that truthfully as "skipped/unavailable" rather
        # than a generic error so the UI never says "Speech error" when the
        # real situation is that AvaLive is simply not running.
        if status == "error" and (
            "unreachable" in str(result.get("error") or "").lower()
            or "identity" in str(result.get("error") or "").lower()
            or "wrong_project" in str(result.get("error") or "").lower()
        ):
            status = "skipped_unavailable"
        out = {k: result.get(k) for k in ("status", "ok", "churn_pct", "threshold_pct", "source")}
        out["status"] = status
        return out
    except Exception:
        return None


def _speak_worker():
    try:
        _SPEAK_LOG.parent.mkdir(parents=True, exist_ok=True)
        logf = open(str(_SPEAK_LOG), "w")
        try:
            proc = subprocess.Popen(
                [str(_PYTHON), str(_SPEAK_GATE), "speak", "--config",
                 str(_SPEAK_CONFIG)],
                cwd=str(_ROOT),
                stdout=logf, stderr=subprocess.STDOUT,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )
            _speak_state["pid"] = proc.pid
            try:
                proc.wait(timeout=240)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        finally:
            logf.close()
    except Exception:
        # Preserve the "error" verdict in the log (single source of truth)
        # if the subprocess could not even be spawned.
        try:
            _SPEAK_LOG.write_text('{"result": {"status": "error"}}', encoding="utf-8")
        except Exception:
            pass
    finally:
        _speak_state["active"] = False
        _speak_state["pid"] = None


def chat_speak():
    """Fire a speak run only if none is active and AvaLive is reachable."""
    if _speak_state["active"]:
        return {"ok": True, "speak": "skipped_active", "active": True}
    missing = [path.relative_to(PACKAGE_ROOT).as_posix()
               for path in (_SPEAK_GATE, _SPEAK_CONFIG)
               if not path.is_file()]
    if not _PYTHON.is_file():
        missing.append("python executable")
    if missing:
        return {"ok": True, "speak": "skipped_unavailable", "active": False,
                "reason": "speech_resources_missing", "missing": missing}
    if not _speak_avalive_online():
        return {"ok": True, "speak": "skipped_unavailable", "active": False,
                "reason": "avalive_offline"}
    with _speak_lock:
        if _speak_state["active"]:
            return {"ok": True, "speak": "skipped_active", "active": True}
        _speak_state["active"] = True
        # Truncate the result log synchronously so status reads "no result"
        # during the run (previously handled by clearing the in-memory copy).
        try:
            _SPEAK_LOG.write_text("", encoding="utf-8")
        except Exception:
            pass
        threading.Thread(target=_speak_worker, daemon=True).start()
    return {"ok": True, "speak": "started", "active": True}


def chat_speak_status():
    return {"ok": True, "active": _speak_state["active"],
            "pid": _speak_state["pid"], "last": _speak_last_result()}
