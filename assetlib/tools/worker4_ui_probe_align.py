"""Probe TextRenderComponent alignment property names/values in 5.8."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.unreal.unreal_bridge import UnrealBridge  # noqa: E402

BRIDGE = UnrealBridge(host="127.0.0.1", port=6766, timeout=120)

code = r"""
import unreal
tr = unreal.TextRenderComponent()
ha = tr.get_editor_property("horizontal_alignment")
va = tr.get_editor_property("vertical_alignment")
__bridge_result__ = {"ha": str(ha), "va": str(va),
                     "ha_type": str(type(ha)), "va_type": str(type(va))}
"""

out = BRIDGE.execute_python(code)
print(json.dumps(out.get("result"), indent=1))
print(out.get("error"))
