from __future__ import annotations

import traceback


def structured_execution_error(exc, *, code="PYTHON_EXECUTION_FAILED", recoverable=False, stdout=""):
    """Return a structured diagnostic while preserving the complete traceback."""
    tb = traceback.format_exc()
    return {
        "ok": False,
        "code": code,
        "error_type": type(exc).__name__,
        "message": str(exc),
        "error": tb,
        "traceback": tb,
        "recoverable": bool(recoverable),
        "stdout": stdout,
    }
