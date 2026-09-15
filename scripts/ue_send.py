#!/usr/bin/env python
"""Send a python command to the running Unreal editor bridge on port 6766.

Usage:
  python scripts/ue_send.py "<python code>"
  python scripts/ue_send.py @path/to/code.py
Prints the JSON response. The code runs on Unreal's main thread; set
__bridge_result__ to return structured data.
"""
import json
import socket
import sys

HOST = "127.0.0.1"
PORT = 6766


def main():
    if len(sys.argv) < 2:
        print("usage: ue_send.py <code> | @file", file=sys.stderr)
        sys.exit(2)
    arg = sys.argv[1]
    if arg.startswith("@"):
        with open(arg[1:], "r", encoding="utf-8-sig") as f:
            code = f.read()
    else:
        code = arg
    payload = {"type": "python", "code": code}
    data = (json.dumps(payload) + "\n").encode("utf-8")
    s = socket.create_connection((HOST, PORT), timeout=180)
    s.sendall(data)
    # read until newline-terminated JSON
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = s.recv(65536)
        if not chunk:
            break
        buf += chunk
    s.close()
    resp = json.loads(buf.decode("utf-8").strip())
    # Pretty print, but keep it compact for large results
    out = json.dumps(resp, indent=2, default=str)
    print(out)
    sys.exit(0 if resp.get("ok") else 1)


if __name__ == "__main__":
    main()