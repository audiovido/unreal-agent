from __future__ import annotations

import os
import uvicorn

if __name__ == "__main__":
    print(f"Unreal Agent backend PID={os.getpid()}", flush=True)
    uvicorn.run(
        "app.served:app",
        host="127.0.0.1",
        port=8765,
        reload=False,
        workers=1,
        log_level="info",
    )
