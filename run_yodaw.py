"""One-command YODAW Code Core launcher."""
from __future__ import annotations

import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    import uvicorn
    host = os.environ.get("YODAW_HOST", "127.0.0.1")
    port = int(os.environ.get("YODAW_PORT", "8790"))
    print(f"YODAW Code Core: http://{host}:{port}", flush=True)
    uvicorn.run("yodaw.api:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
