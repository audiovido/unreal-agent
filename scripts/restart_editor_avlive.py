"""Safely restart Unreal Editor on the AvaLive project and wait until the
Unreal Agent bridge is fully READY. Idempotent: if an editor is already open on
the target project it is left in place; otherwise a fresh editor boots.

The real AvaLive .uproject is nested (AvaLive/AvaLive/AvaLive.uproject); the
flattened path the spec references does not exist on disk.
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.unreal import project_manager as pm
from tools.unreal.unreal_bridge import UnrealBridge
from tools.unreal import project_context as pc

REAL_AVLIVE = r"C:\Users\Shadow\Desktop\AvaLive\AvaLive\AvaLive.uproject"


def main():
    bridge = UnrealBridge(timeout=30)
    print("[1] Saving dirty project (safe close)...")
    try:
        r = bridge.execute_python(
            "unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)"
        )
        print("    save:", r.get("ok"))
    except Exception as exc:
        print("    save warn:", type(exc).__name__, exc)

    print("[2] Checking current editor identity...")
    ident = bridge.get_project_identity()
    inner = ident.get("result") or {}
    current = inner.get("project_name") if inner.get("ok") else None
    current_path = inner.get("project_path")
    print("    current editor project:", current, "|", current_path)

    already = bool(current_path and str(current_path).lower() == str(REAL_AVLIVE).lower())
    if already:
        print("[3] Editor already open on AvaLive -> reusing (fresh bridge check).")
    else:
        print("[3] Stopping current Unreal Editor...")
        stop = pm._stop_current_editor()
        print("    stop ok:", stop.get("ok"), "|", stop.get("error", ""))

        # Wait for the bridge port to be released before relaunching.
        deadline = time.time() + 40
        while time.time() < deadline:
            if not pm._bridge_socket_ready():
                break
            time.sleep(1)

        print("[4] Reopening AvaLive and waiting for bridge READY...")
        opened = pm.open_project(REAL_AVLIVE)
        print("    open ok:", opened.get("ok"), "| editor_pid:", opened.get("editor_pid"))
        if not opened.get("ok"):
            print("    open error:", opened.get("error"))
            for k in ("bridge_ready", "error"):
                if isinstance(opened.get(k), dict):
                    print("      ", k, ":", opened.get(k))
            sys.exit(2)

    # Final hard verification: bridge READY + identity == AvaLive.
    for attempt in range(20):
        ping = bridge.ping()
        ident = bridge.get_project_identity()
        inner = ident.get("result") or {}
        ok = (
            (ping.get("ok") is True)
            and (inner.get("ok") is True)
            and inner.get("project_name") == "AvaLive"
        )
        if ok:
            print("[5] Bridge READY on project:", inner.get("project_name"))
            print("    path:", inner.get("project_path"))
            print("    engine:", inner.get("engine"))
            ctx = pc.load_active_context()
            print("    persisted project:", ctx.get("project_name"), "| validity:", ctx.get("validity"))
            return 0
        time.sleep(2)
    print("FAIL: bridge/identity not READY on AvaLive")
    print("  last ping:", ping)
    print("  last identity:", ident)
    return 3


if __name__ == "__main__":
    sys.exit(main())