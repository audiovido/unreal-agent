"""scripts/mcp_gateway_validate.py — LIVE end-to-end validation of the Aivido
MCP gateway using the official MCP Python client SDK over Streamable HTTP,
exactly the way ClickUp Brain / Super Agents connect.

Drives the gateway (http://127.0.0.1:8844/mcp by default, override with
AIVIDO_MCP_URL) against the REAL Aivido backend on 127.0.0.1:8765 and
reports PASS/FAIL per step with a final tally.

Run:  .venv\\Scripts\\python.exe scripts/mcp_gateway_validate.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx2 as httpx  # noqa: E402
from mcp import ClientSession  # noqa: E402
from mcp.client.streamable_http import streamable_http_client  # noqa: E402

GATEWAY_URL = os.environ.get(
    "AIVIDO_MCP_URL", "http://127.0.0.1:8844/mcp")
KEY_FILE = ROOT / "config" / "mcp_gateway.key"

REQUIRED_TOOLS = {
    "get_status", "start_task", "get_task_status", "run_validation",
    "get_evidence", "retry_task", "cancel_task",
}

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def _short(value, limit=300):
    s = json.dumps(value, default=str, ensure_ascii=False)
    return s if len(s) <= limit else s[:limit] + "..."


def _tool_text(result) -> str:
    """Extract text content from an MCP CallToolResult."""
    parts = []
    for c in getattr(result, "content", []) or []:
        t = getattr(c, "text", None)
        if t:
            parts.append(str(t))
        structured = getattr(c, "structuredContent", None) or getattr(c, "structured", None)
        if structured:
            parts.append(json.dumps(structured, default=str))
    if not parts:
        return json.dumps(getattr(result, "model_dump", lambda: {})() or {}, default=str)
    return "\n".join(parts)


def _as_dict(result) -> dict:
    text = _tool_text(result)
    try:
        return json.loads(text)
    except Exception:
        return {"raw": text}


async def main() -> int:
    key = KEY_FILE.read_text(encoding="utf-8").strip() if KEY_FILE.exists() else ""
    if not key:
        record("api_key", False, "config/mcp_gateway.key missing")
        return 1

    headers = {"Authorization": f"Bearer {key}"}

    async with httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(60.0)) as http_client:
        try:
            transport = streamable_http_client(
                GATEWAY_URL, http_client=http_client)
            async with transport as streams:
                read_stream, write_stream = streams[0], streams[1]
                async with ClientSession(read_stream, write_stream) as session:
                    # 1. handshake
                    try:
                        init = await session.initialize()
                        info = getattr(init, "server_info", None) or getattr(
                            init, "serverInfo", None)
                        record(
                            "handshake",
                            True,
                            f"{info.name} v{info.version} "
                            f"protocol {init.protocol_version}",
                        )
                    except Exception as exc:
                        record("handshake", False, str(exc))
                        return 1

                    # 2. tool listing
                    try:
                        tools = await session.list_tools()
                        names = {t.name for t in tools.tools}
                        missing = sorted(REQUIRED_TOOLS - names)
                        record(
                            "tool_listing",
                            not missing,
                            f"exposed={sorted(names)} missing={missing or 'none'}",
                        )
                    except Exception as exc:
                        record("tool_listing", False, str(exc))
                        return 1

                    # 3. get_status
                    try:
                        r = _as_dict(await session.call_tool("get_status", {}))
                        record(
                            "get_status",
                            bool(r.get("ok")) and r.get("result", {}).get("backend_version"),
                            _short(r.get("result")),
                        )
                    except Exception as exc:
                        record("get_status", False, str(exc))

                    # 4. start_task (harmless real mission through the pipeline)
                    task_id = None
                    try:
                        r = _as_dict(await session.call_tool(
                            "start_task",
                            {"prompt": (
                                "Spawn a StaticMeshActor cube named UA_MCP_Test "
                                "at location [300, 0, 100] with scale [0.5, 0.5, 0.5] "
                                "in the current level, verify the actor exists via "
                                "get_actor, and capture viewport evidence.")},
                        ))
                        task_id = r.get("task_id")
                        record(
                            "start_task",
                            bool(task_id) and r.get("status") == "accepted",
                            _short({"task_id": task_id, "status": r.get("status"),
                                    "result": r.get("result")}),
                        )
                    except Exception as exc:
                        record("start_task", False, str(exc))

                    # 5. get_task_status until real terminal state
                    if task_id:
                        terminal = None
                        for _ in range(40):
                            try:
                                r = _as_dict(await session.call_tool(
                                    "get_task_status", {"task_id": task_id}))
                            except Exception as exc:
                                record("get_task_status", False, str(exc))
                                terminal = "error"
                                break
                            st = r.get("status")
                            if st in ("complete", "failed", "blocked"):
                                terminal = st
                                record(
                                    "get_task_status",
                                    True,
                                    _short({"status": st, "stage": r.get("stage"),
                                            "verdict": (r.get("result") or {}).get("verdict"),
                                            "errors": r.get("errors")}),
                                )
                                break
                            await asyncio.sleep(4)
                        if terminal is None:
                            record("get_task_status", False,
                                   "no terminal state after 160s (still "
                                   f"{r.get('status') if 'r' in dir() else '?'})")

                    # 6. run_validation (real results)
                    if task_id:
                        try:
                            r = _as_dict(await session.call_tool(
                                "run_validation", {"task_id": task_id}))
                            verdict = (r.get("result") or {}).get("verdict")
                            record(
                                "run_validation",
                                bool(verdict),
                                _short({"stage": r.get("stage"),
                                        "verdict": verdict,
                                        "errors": r.get("errors")}),
                            )
                        except Exception as exc:
                            record("run_validation", False, str(exc))

                    # 7. get_evidence (real paths)
                    if task_id:
                        try:
                            r = _as_dict(await session.call_tool(
                                "get_evidence", {"task_id": task_id}))
                            ev = r.get("evidence") or {}
                            record(
                                "get_evidence",
                                r.get("ok") is True,
                                _short({"evidence_paths": ev.get("paths"),
                                        "artifacts": ev.get("artifacts"),
                                        "mission_log": ev.get("mission_log")}),
                            )
                        except Exception as exc:
                            record("get_evidence", False, str(exc))

                    # 8. cancel_task on a fresh mission with REAL steps
                    cancel_id = None
                    try:
                        r = _as_dict(await session.call_tool(
                            "start_task",
                            {"prompt": (
                                "Spawn a StaticMeshActor cube named UA_MCP_CancelProbe "
                                "at location [400, 0, 100], verify it exists via get_actor, "
                                "then move it to [500, 0, 100] and verify again.")},
                        ))
                        cancel_id = r.get("task_id")
                        record("cancel_prep", bool(cancel_id),
                               f"cancel target task_id={cancel_id}")
                    except Exception as exc:
                        record("cancel_prep", False, str(exc))

                    if cancel_id:
                        try:
                            r = _as_dict(await session.call_tool(
                                "cancel_task", {"task_id": cancel_id}))
                            record(
                                "cancel_task",
                                r.get("status") in ("blocked", "complete", "failed"),
                                _short({"status": r.get("status"),
                                        "verdict": (r.get("result") or {}).get("verdict")}),
                            )
                        except Exception as exc:
                            record("cancel_task", False, str(exc))

                        # Confirm the terminal state is REAL via get_task_status
                        final_status = None
                        for _ in range(20):
                            try:
                                r = _as_dict(await session.call_tool(
                                    "get_task_status", {"task_id": cancel_id}))
                            except Exception:
                                break
                            if r.get("status") in (
                                    "complete", "failed", "blocked"):
                                final_status = r.get("status")
                                break
                            await asyncio.sleep(3)
                        record(
                            "cancel_confirmed_real",
                            final_status is not None,
                            f"final real status={final_status or 'still running'}",
                        )

                    # 9. retry_task on the cancelled mission (real resume)
                    if cancel_id:
                        try:
                            r = _as_dict(await session.call_tool(
                                "retry_task", {"task_id": cancel_id}))
                            record(
                                "retry_task",
                                bool(r.get("ok")) and r.get("status") in (
                                    "complete", "failed", "blocked", "executing"),
                                _short({"status": r.get("status"),
                                        "stage": r.get("stage"),
                                        "verdict": (r.get("result") or {}).get("verdict")}),
                            )
                        except Exception as exc:
                            record("retry_task", False, str(exc))
        except Exception as exc:
            record("connect", False, str(exc))
            return 1

    # 10. auth rejection (invalid token -> 401)
    try:
        async with httpx.AsyncClient(
                headers={"Authorization": "Bearer invalid-token"},
                timeout=httpx.Timeout(20.0)) as bad_client:
            resp = await bad_client.post(
                GATEWAY_URL,
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                      "params": {"protocolVersion": "2025-03-26",
                                 "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
            )
        record("auth_rejection", resp.status_code == 401,
               f"invalid token -> HTTP {resp.status_code}")
    except Exception as exc:
        record("auth_rejection", False, str(exc))

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print("\n" + "=" * 60)
    print(f"RESULT: {passed}/{total} passed")
    for name, ok, detail in RESULTS:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    print("=" * 60)
    return 0 if passed == total else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))