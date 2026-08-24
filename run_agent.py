from __future__ import annotations

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.api:app",
        host="0.0.0.0",
        port=8765,
        reload=True,
        reload_dirs=[
            "app",
            "core",
            "tools",
        ],
        log_level="info",
    )
