"""config.py — UNREAL CODER configuration + secret hygiene.

ONE module that owns:
  - configuration values (env override -> config file -> safe default)
  - required vs optional vs secret classification
  - redaction of secrets for logs, errors and mission payloads

Never log raw API keys. Any string that looks like a secret (by key name or
by shape) is replaced by a stable short fingerprint (first 4 chars + length)
so operators can tell two keys apart without exposing either.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "config" / "settings.json"

# ---------------------------------------------------------------------------
# Secret classification
# ---------------------------------------------------------------------------

# Key-name fragments that mark a value as a secret wherever it appears.
SECRET_KEY_MARKERS = (
    "api_key", "apikey", "api-key", "token", "secret", "password",
    "passwd", "authorization", "credential", "private_key", "bearer",
)

# Environment variable names that carry secrets.
SECRET_ENV_NAMES = {
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "REPLICATE_API_TOKEN",
    "HF_TOKEN", "GROQ_API_KEY", "MISTRAL_API_KEY", "TOGETHER_API_KEY",
    "UNREAL_AGENT_REMOTE_API_KEY",
}

# Value shapes that look like secrets even under an innocent key.
_SECRET_VALUE_SHAPES = (
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b"),          # OpenAI-style
    re.compile(r"\bey[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),  # JWT-ish
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b"),   # Slack-style
)

_REDACTED = "[REDACTED]"


def is_secret_key(key: str) -> bool:
    k = str(key or "").lower()
    return any(marker in k for marker in SECRET_KEY_MARKERS)


def looks_like_secret(value: str) -> bool:
    text = str(value or "")
    return any(shape.search(text) for shape in _SECRET_VALUE_SHAPES)


def redact_value(value: Any, key: str = "") -> Any:
    """Redact one scalar. Keys keep their identity, values get a fingerprint."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return redact(value, key_hint=key)
    text = str(value)
    if not text:
        return text
    if (key and is_secret_key(key)) or looks_like_secret(text):
        return f"{_REDACTED}(<{len(text)} chars, fp={text[:4]}...>)"
    return value


def redact(data: Any, key_hint: str = "", _depth: int = 0) -> Any:
    """Deep-redact secrets from any JSON-able structure.

    Recurses dicts/lists; redacts by key name OR by value shape. Bounded
    depth so hostile payloads cannot blow the stack.
    """
    if _depth > 12:
        return data
    if isinstance(data, dict):
        out: Dict[str, Any] = {}
        for k, v in data.items():
            out[str(k)] = redact_value(v, key=str(k)) \
                if not isinstance(v, (dict, list)) else redact(v, key_hint=str(k), _depth=_depth + 1)
        return out
    if isinstance(data, (list, tuple)):
        return [redact(item, key_hint=key_hint, _depth=_depth + 1) for item in data]
    return redact_value(data, key=key_hint)


def redact_text(text: str) -> str:
    """Redact secret-shaped substrings inside free text (log lines, errors)."""
    result = str(text or "")
    for shape in _SECRET_VALUE_SHAPES:
        result = shape.sub(
            lambda m: f"{_REDACTED}(<{len(m.group(0))} chars>)", result)
    # env-style assignments: KEY=... where KEY names a secret
    result = re.sub(
        r"(?i)\b([A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD|KEY)[A-Z0-9_]*)"
        r"\s*[=:]\s*([^\s,;\"']{6,})",
        lambda m: f"{m.group(1)}={_REDACTED}",
        result,
    )
    return result


# ---------------------------------------------------------------------------
# Configuration values
# ---------------------------------------------------------------------------

def _load_config_file() -> Dict[str, Any]:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def get_setting(key: str, env_names: Tuple[str, ...] = (),
                default: Any = None) -> Any:
    """env override -> config file -> default."""
    for name in env_names:
        value = os.getenv(name)
        if value not in (None, ""):
            return value
    cfg = _load_config_file()
    if key in cfg and cfg[key] not in (None, ""):
        return cfg[key]
    return default


def config_snapshot() -> Dict[str, Any]:
    """All known configuration WITH secrets already redacted.

    This is the ONLY sanctioned way to dump configuration for doctor/logs.
    """
    cfg = _load_config_file()
    env: Dict[str, Any] = {}
    for name in sorted(os.environ):
        if name.startswith("UNREAL_AGENT_") or name in SECRET_ENV_NAMES:
            env[name] = redact_value(os.environ[name], key=name)
    merged = {**cfg, **{k.lower(): v for k, v in env.items()}}
    return redact({
        "config_file": str(CONFIG_FILE),
        "values": merged,
        "environment": env,
    })


# Known configuration surface (for doctor + docs).
CONFIG_SURFACE: List[Dict[str, Any]] = [
    {"key": "unreal_engine", "env": "UNREAL_AGENT_ENGINE_DIR",
     "required": False, "secret": False,
     "desc": "Unreal Engine root (contains Engine/Binaries/...)."},
    {"key": "ollama_url", "env": "UNREAL_AGENT_OLLAMA_URL",
     "required": False, "secret": False,
     "desc": "Local model/Ollama base URL."},
    {"key": "fast_model", "env": "UNREAL_AGENT_FAST_MODEL",
     "required": False, "secret": False,
     "desc": "Small/fast local model name."},
    {"key": "expert_model", "env": "UNREAL_AGENT_DEFAULT_MODEL",
     "required": False, "secret": False,
     "desc": "Heavy Unreal specialist model name."},
    {"key": "vision_model", "env": "UNREAL_AGENT_VISION_MODEL",
     "required": False, "secret": False,
     "desc": "Vision model for visual review (local or remote)."},
    {"key": "remote_vision_url", "env": "UNREAL_AGENT_REMOTE_VISION_URL",
     "required": False, "secret": False,
     "desc": "Optional remote OpenAI-compatible vision endpoint."},
    {"key": "remote_vision_api_key", "env": "UNREAL_AGENT_REMOTE_API_KEY",
     "required": False, "secret": True,
     "desc": "API key for the remote vision provider. NEVER logged."},
]
