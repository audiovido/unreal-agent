from pathlib import Path
import base64

ROOT = Path(r"C:\Users\Shadow\Desktop\Unreal-Agent")
ORCH = ROOT / "core" / "orchestrator.py"
API = ROOT / "app" / "api.py"

orch = ORCH.read_text(encoding="utf-8-sig")
api = API.read_text(encoding="utf-8-sig")

START = "# >>> VISUAL_REVIEW_LOOP_V4 >>>"
END = "# <<< VISUAL_REVIEW_LOOP_V4 <<<"

# Idempotent reinstall.
if START in orch and END in orch:
    a = orch.index(START)
    b = orch.index(END, a) + len(END)
    orch = orch[:a].rstrip() + "\n\n" + orch[b:].lstrip()

required = [
    "AVAILABLE_MODELS",
    "FAST_MODEL",
    "REASONING_MODEL",
    "CODER_MODEL",
    "def create_execution_plan(task):",
    "def build_executor_system(",
    "def runtime_info():",
]
for token in required:
    if token not in orch:
        raise RuntimeError("Missing orchestrator marker: " + token)

wrapper = base64.b64decode("IyA+Pj4gVklTVUFMX1JFVklFV19MT09QX1Y0ID4+PgoKVklTSU9OX01PREVMID0gb3MuZ2V0ZW52KAogICAgIlVOUkVBTF9BR0VOVF9WSVNJT05fTU9ERUwiLAogICAgInF3ZW4zLXZsOjhiLWluc3RydWN0IiwKKQoKVklTSU9OX01PREVMX0FWQUlMQUJMRSA9IFZJU0lPTl9NT0RFTCBpbiBBVkFJTEFCTEVfTU9ERUxTCgpfY3JlYXRlX2V4ZWN1dGlvbl9wbGFuX3YzID0gY3JlYXRlX2V4ZWN1dGlvbl9wbGFuCl9idWlsZF9leGVjdXRvcl9zeXN0ZW1fdjMgPSBidWlsZF9leGVjdXRvcl9zeXN0ZW0KX3J1bnRpbWVfaW5mb192MyA9IHJ1bnRpbWVfaW5mbwoKCmRlZiBzaG91bGRfdXNlX3Zpc2lvbih0YXNrKToKICAgIHRleHQgPSBzdHIodGFzaykubG93ZXIoKQoKICAgIHZpc3VhbF90ZXJtcyA9ICgKICAgICAgICAidWkiLAogICAgICAgICJ1eCIsCiAgICAgICAgIndpZGdldCIsCiAgICAgICAgImh1ZCIsCiAgICAgICAgIm1lbnUiLAogICAgICAgICJpbnRlcmZhY2UiLAogICAgICAgICJyb29tIiwKICAgICAgICAiZW52aXJvbm1lbnQiLAogICAgICAgICJsZXZlbCBkZXNpZ24iLAogICAgICAgICJzY2VuZSIsCiAgICAgICAgImxpZ2h0aW5nIiwKICAgICAgICAibGlnaHQiLAogICAgICAgICJtYXRlcmlhbCIsCiAgICAgICAgInRleHR1cmUiLAogICAgICAgICJ2aXN1YWwiLAogICAgICAgICJsb29rIiwKICAgICAgICAiY29tcG9zaXRpb24iLAogICAgICAgICJjaW5lbWF0aWMiLAogICAgICAgICJjYW1lcmEiLAogICAgICAgICJiZWF1dGlmdWwiLAogICAgICAgICJhYWEiLAogICAgICAgICJ3b3JsZCIsCiAgICAgICAgImxhbmRzY2FwZSIsCiAgICAgICAgImludGVyaW9yIiwKICAgICAgICAiZXh0ZXJpb3IiLAogICAgICAgICLYp9iq2KfZgiIsCiAgICAgICAgItmF2K3bjNi3IiwKICAgICAgICAi2YTZiNmEIiwKICAgICAgICAi2LXYrdmG2YciLAogICAgICAgICLZhtmI2LEiLAogICAgICAgICLZhtmI2LHZvtix2K/Yp9iy24wiLAogICAgICAgICLZhdiq2LHbjNin2YQiLAogICAgICAgICLYqtqp2LPahtixIiwKICAgICAgICAi2LjYp9mH2LEiLAogICAgICAgICLZiNuM2pjZiNin2YQiLAogICAgICAgICLYr9mI2LHYqNuM2YYiLAogICAgICAgICLYs9uM2YbZhdin2KrbjNqpIiwKICAgICAgICAi2LHYp9io2Lcg2qnYp9ix2KjYsduMIiwKICAgICAgICAi2YXZhtmIIiwKICAgICAgICAi24zZiCDYotuMIiwKICAgICAgICAi24zZiNin24wiLAogICAgICAgICLbjNmIINin24zaqdizIiwKICAgICAgICAi2LLbjNio2KciLAogICAgKQoKICAgIHJldHVybiBhbnkodGVybSBpbiB0ZXh0IGZvciB0ZXJtIGluIHZpc3VhbF90ZXJtcykKCgpkZWYgY3JlYXRlX2V4ZWN1dGlvbl9wbGFuKHRhc2spOgogICAgcGxhbiA9IF9jcmVhdGVfZXhlY3V0aW9uX3BsYW5fdjModGFzaykKCiAgICBpZiBub3QgaXNpbnN0YW5jZShwbGFuLCBkaWN0KToKICAgICAgICByZXR1cm4gcGxhbgoKICAgIHZpc2lvbl9yZXF1aXJlZCA9ICgKICAgICAgICBWSVNJT05fTU9ERUxfQVZBSUxBQkxFCiAgICAgICAgYW5kIHNob3VsZF91c2VfdmlzaW9uKHRhc2spCiAgICApCgogICAgcm91dGluZyA9IHBsYW4uc2V0ZGVmYXVsdCgiX3JvdXRpbmciLCB7fSkKICAgIHJvdXRpbmdbInZpc2lvbl9yZXF1aXJlZCJdID0gdmlzaW9uX3JlcXVpcmVkCiAgICByb3V0aW5nWyJ2aXNpb25fbW9kZWwiXSA9ICgKICAgICAgICBWSVNJT05fTU9ERUwgaWYgdmlzaW9uX3JlcXVpcmVkIGVsc2UgTm9uZQogICAgKQoKICAgIGlmIHZpc2lvbl9yZXF1aXJlZDoKICAgICAgICBzdGVwcyA9IHBsYW4uc2V0ZGVmYXVsdCgic3RlcHMiLCBbXSkKICAgICAgICB2aXN1YWxfc3RlcCA9ICgKICAgICAgICAgICAgIkFmdGVyIG1lYW5pbmdmdWwgdmlzdWFsIG11dGF0aW9ucywgcnVuIHRoZSBhcHByb3ZlZCAiCiAgICAgICAgICAgICJWaXN1YWwgUmV2aWV3IHRvb2wsIGluc3BlY3QgdGhlIHNjcmVlbnNob3QgZmVlZGJhY2ssICIKICAgICAgICAgICAgImZpeCB2aXNpYmxlIGlzc3VlcywgYW5kIHJlcGVhdCB1bnRpbCB0aGUgdmlzdWFsIHNjb3JlICIKICAgICAgICAgICAgImlzIGF0IGxlYXN0IDgvMTAgb3IgZm91ciByZXZpZXcgcGFzc2VzIGhhdmUgYmVlbiB1c2VkLiIKICAgICAgICApCiAgICAgICAgaWYgdmlzdWFsX3N0ZXAgbm90IGluIHN0ZXBzOgogICAgICAgICAgICBzdGVwcy5hcHBlbmQodmlzdWFsX3N0ZXApCgogICAgICAgIHN1Y2Nlc3MgPSBwbGFuLnNldGRlZmF1bHQoInN1Y2Nlc3NfY3JpdGVyaWEiLCBbXSkKICAgICAgICB2aXN1YWxfc3VjY2VzcyA9ICgKICAgICAgICAgICAgIkZpbmFsIHZpc2libGUgVW5yZWFsIHJlc3VsdCBpcyBpbmRlcGVuZGVudGx5IHJldmlld2VkICIKICAgICAgICAgICAgImJ5IHRoZSB2aXNpb24gbW9kZWwgYW5kIGhhcyBubyBjcml0aWNhbCB2aXNpYmxlIGlzc3VlLiIKICAgICAgICApCiAgICAgICAgaWYgdmlzdWFsX3N1Y2Nlc3Mgbm90IGluIHN1Y2Nlc3M6CiAgICAgICAgICAgIHN1Y2Nlc3MuYXBwZW5kKHZpc3VhbF9zdWNjZXNzKQoKICAgIHJldHVybiBwbGFuCgoKZGVmIGJ1aWxkX2V4ZWN1dG9yX3N5c3RlbShwbGFuKToKICAgIGJhc2UgPSBfYnVpbGRfZXhlY3V0b3Jfc3lzdGVtX3YzKHBsYW4pCgogICAgaWYgbm90IGlzaW5zdGFuY2UocGxhbiwgZGljdCk6CiAgICAgICAgcmV0dXJuIGJhc2UKCiAgICByb3V0aW5nID0gcGxhbi5nZXQoIl9yb3V0aW5nIiwge30pCgogICAgaWYgbm90IHJvdXRpbmcuZ2V0KCJ2aXNpb25fcmVxdWlyZWQiKToKICAgICAgICByZXR1cm4gYmFzZQoKICAgIHZpc3VhbF9ydWxlcyA9IHIiIiIKClZJU1VBTCBRQSBMT09QIElTIFJFUVVJUkVEIEZPUiBUSElTIFRBU0suCgpZb3UgaGF2ZSBhbiBhcHByb3ZlZCByZWFkLW9ubHkgdmlzdWFsIHJldmlldyBjb21tYW5kLgoKVXNlIHRoZSBleGlzdGluZyBydW5fcG93ZXJzaGVsbCB0b29sIHdpdGggRVhBQ1RMWSBvbmUgb2YgdGhlc2UKZXF1aXZhbGVudCBjb21tYW5kIHN0cmluZ3MgYW5kIGRvIG5vdCBhZGQgYW55IG90aGVyIFBvd2VyU2hlbGw6CgomICIkZW52OkxPQ0FMQVBQREFUQVxVbnJlYWxBZ2VudFx2aXNpb25fcmV2aWV3LnBzMSIKCm9yLCBpZiBlbnZpcm9ubWVudCB2YXJpYWJsZXMgYXJlIG5vdCBleHBhbmRlZCBieSB0aGUgdG9vbDoKCiYgIkM6XFVzZXJzXFNoYWRvd1xBcHBEYXRhXExvY2FsXFVucmVhbEFnZW50XHZpc2lvbl9yZXZpZXcucHMxIgoKVGhlIGNvbW1hbmQgY2FwdHVyZXMgdGhlIFVucmVhbCBFZGl0b3Igd2luZG93IGFuZCByZXR1cm5zIEpTT04KZnJvbSB0aGUgbG9jYWwgdmlzaW9uIG1vZGVsLgoKUnVsZXM6CjEuIFVzZSB2aXN1YWwgcmV2aWV3IG9ubHkgYWZ0ZXIgdGhlcmUgaXMgc29tZXRoaW5nIG1lYW5pbmdmdWwgdG8gaW5zcGVjdC4KMi4gVHJlYXQgY2FwdHVyZV9xdWFsaXR5PSJiYWQiIG9yICJvY2NsdWRlZCIgYXMgaW52YWxpZCBldmlkZW5jZS4KMy4gTmV2ZXIgbWFrZSBkZXN0cnVjdGl2ZSBjaGFuZ2VzIGJhc2VkIG9uIGFuIHVudXNhYmxlIHNjcmVlbnNob3QuCjQuIElmIHBhc3M9ZmFsc2Ugb3Igc2NvcmU8OCwgYXBwbHkgdGhlIGNvbmNyZXRlIHZpc2libGUgZml4ZXMgYW5kIHJldmlldyBhZ2Fpbi4KNS4gTWF4aW11bSBmb3VyIHZpc3VhbCByZXZpZXcgcGFzc2VzIHBlciB0YXNrLgo2LiBEbyBub3QgZGVjbGFyZSBhIHZpc3VhbC9VSS9lbnZpcm9ubWVudCB0YXNrIGNvbXBsZXRlIHdpdGhvdXQKICAgYXQgbGVhc3Qgb25lIHVzYWJsZSB2aXN1YWwgcmV2aWV3IGFmdGVyIHRoZSBmaW5hbCBtZWFuaW5nZnVsIG11dGF0aW9uLgo3LiBWaXN1YWwgcmV2aWV3IGRvZXMgbm90IHJlcGxhY2UgdGVjaG5pY2FsIHZlcmlmaWNhdGlvbjsgY29tcGlsZSwKICAgcmVhZC1iYWNrLCBzYXZlLCBhbmQgb3RoZXIgaW5kZXBlbmRlbnQgY2hlY2tzIGFyZSBzdGlsbCByZXF1aXJlZC4KOC4gTmV2ZXIgbW9kaWZ5IHRoZSB2aXN1YWxfcmV2aWV3LnBzMSBmaWxlLgoiIiIKCiAgICByZXR1cm4gc3RyKGJhc2UpICsgdmlzdWFsX3J1bGVzCgoKZGVmIHJ1bnRpbWVfaW5mbygpOgogICAgaW5mbyA9IF9ydW50aW1lX2luZm9fdjMoKQogICAgaW5mb1sidmVyc2lvbiJdID0gIkFkYXB0aXZlIFJ1bnRpbWUgdjQiCiAgICBpbmZvWyJ2aXNpb25fbW9kZWwiXSA9ICgKICAgICAgICBWSVNJT05fTU9ERUwKICAgICAgICBpZiBWSVNJT05fTU9ERUxfQVZBSUxBQkxFCiAgICAgICAgZWxzZSBOb25lCiAgICApCiAgICBpbmZvWyJ2aXNpb25fbW9kZWxfYXZhaWxhYmxlIl0gPSBWSVNJT05fTU9ERUxfQVZBSUxBQkxFCiAgICByZXR1cm4gaW5mbwoKIyA8PDwgVklTVUFMX1JFVklFV19MT09QX1Y0IDw8PA==").decode("utf-8")

cli_marker = 'if __name__ == "__main__":'
pos = orch.find(cli_marker)
if pos < 0:
    raise RuntimeError("Could not find orchestrator CLI marker.")

orch = (
    orch[:pos].rstrip()
    + "\n\n"
    + wrapper.strip()
    + "\n\n"
    + orch[pos:]
)

# API imports.
if "    VISION_MODEL,\n" not in api:
    if "    HEAVY_MODEL_AVAILABLE,\n" in api:
        needle = "    HEAVY_MODEL_AVAILABLE,\n"
    elif "    CODER_MODEL,\n" in api:
        needle = "    CODER_MODEL,\n"
    else:
        raise RuntimeError("Could not find model import anchor in app/api.py.")

    api = api.replace(
        needle,
        needle + "    VISION_MODEL,\n    VISION_MODEL_AVAILABLE,\n",
        1,
    )

api = api.replace('version="3.0.0"', 'version="4.0.0"', 1)
api = api.replace('version="2.0.0"', 'version="4.0.0"', 1)
api = api.replace('"version": "Adaptive API v3"', '"version": "Adaptive API v4"', 1)
api = api.replace('"version": "Adaptive API v2"', '"version": "Adaptive API v4"', 1)

# /api/status model exposure.
if '"vision": (' not in api:
    needle = '"coder": CODER_MODEL,'
    if needle not in api:
        raise RuntimeError("Could not find coder model in /api/status.")
    api = api.replace(
        needle,
        '"coder": CODER_MODEL,\n'
        '            "vision": (\n'
        '                VISION_MODEL\n'
        '                if VISION_MODEL_AVAILABLE\n'
        '                else None\n'
        '            ),',
        1,
    )

# Remove older approval wrapper if a prior v4 attempt exists.
A_START = "# >>> VISION_SAFE_APPROVAL_V4 >>>"
A_END = "# <<< VISION_SAFE_APPROVAL_V4 <<<"
if A_START in api and A_END in api:
    a = api.index(A_START)
    b = api.index(A_END, a) + len(A_END)
    api = api[:a].rstrip() + "\n\n" + api[b:].lstrip()

approval = r"""
# >>> VISION_SAFE_APPROVAL_V4 >>>

_requires_approval_v3 = requires_approval


def _vision_collect_strings(value):
    out = []

    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            out.extend(_vision_collect_strings(v))
    elif isinstance(value, (list, tuple)):
        for v in value:
            out.extend(_vision_collect_strings(v))

    return out


def requires_approval(action, args):
    if action == "run_powershell":
        allowed = ('& "$env:LOCALAPPDATA\\\\UnrealAgent\\\\vision_review.ps1"', '& "C:\\\\Users\\\\Shadow\\\\AppData\\\\Local\\\\UnrealAgent\\\\vision_review.ps1"', 'C:\\\\Users\\\\Shadow\\\\AppData\\\\Local\\\\UnrealAgent\\\\vision_review.ps1')

        values = {
            s.strip()
            for s in _vision_collect_strings(args)
        }

        if values and values.issubset(allowed):
            return False

    return _requires_approval_v3(action, args)

# <<< VISION_SAFE_APPROVAL_V4 <<<
"""

route_candidates = [
    '@app.get("/")',
    "@app.get('/')",
    '@app.get("/api/status")',
]
route_pos = -1
for marker in route_candidates:
    route_pos = api.find(marker)
    if route_pos >= 0:
        break

if route_pos < 0:
    raise RuntimeError("Could not find API route insertion point.")

api = (
    api[:route_pos].rstrip()
    + "\n\n"
    + approval.strip()
    + "\n\n"
    + api[route_pos:]
)

# Validate generated source before writing live files.
compile(orch, str(ORCH), "exec")
compile(api, str(API), "exec")

ORCH.write_text(orch, encoding="utf-8")
API.write_text(api, encoding="utf-8")

print("VISION_LOOP_SOURCE_VALID=PASS")
