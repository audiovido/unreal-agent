#!/usr/bin/env python
"""Send a screenshot to the local vision model (qwen3-vl) with a custom prompt.

Usage:
  python scripts/avlive_vision.py <image.png> "<prompt>"
  python scripts/avlive_vision.py <image.png> @prompt_file.txt
Prints the raw model text response.
"""
import base64
import json
import os
import sys

import requests

OLLAMA = os.getenv("UNREAL_AGENT_OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
MODEL = os.getenv("UNREAL_AGENT_VISION_MODEL", "qwen3-vl:8b-instruct")


def main():
    if len(sys.argv) < 3:
        print("usage: avlive_vision.py <image.png> <prompt>|@file", file=sys.stderr)
        sys.exit(2)
    img = sys.argv[1]
    arg = sys.argv[2]
    if arg.startswith("@"):
        with open(arg[1:], "r", encoding="utf-8") as f:
            prompt = f.read()
    else:
        prompt = arg
    if not os.path.isfile(img):
        print("image not found:", img, file=sys.stderr)
        sys.exit(2)
    b64 = base64.b64encode(open(img, "rb").read()).decode("ascii")
    body = {
        "model": MODEL,
        "stream": False,
        "options": {"temperature": 0},
        "messages": [{"role": "user", "content": prompt, "images": [b64]}],
    }
    r = requests.post(OLLAMA, json=body, timeout=600)
    r.raise_for_status()
    content = str(r.json().get("message", {}).get("content", ""))
    print(content)


if __name__ == "__main__":
    main()