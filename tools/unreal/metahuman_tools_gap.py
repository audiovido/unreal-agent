"""MetaHuman gap-closure batch 6 (UE 5.8 bridge).

Surface probed live before implementation: the running ASSET_Showcase2 session
mirrors the MetaHumanSDK plugin ONLY - 26 symbols across MetaHumanSDKRuntime and
MetaHumanSDKEditor modules (runtime components MetaHumanComponentUE/Base,
MetaHumanCustomizableBodyPart, import/verification options structs, the
MetaHumanAssetType / MetaHumanQualityLevel enums, the MetaHumanPackageFactory
UFactory, and the five VerifyMetaHuman* verification-rule CLASSES).

CLOSED surface recorded, not faked:
  - MetaHumanIdentity / MetaHumanIdentityParts / MetaHumanIdentityPose etc.
    live in the MetaHumanAnimator/MetaHumanIdentityEditor C++ module, which is
    NOT enabled in this project and NOT mirrored to Python (0 symbols).
  - The five VerifyMetaHuman* helpers are rule classes, not string-callable
    verifiers - calling them with a package path raises the exact nativize
    error captured in the evidence.
  - MetaHumanPackageFactory.supported_class defaults to core Object and
    script_factory_can_import() returns False for empty / .mhasset paths -
    a MetaHuman archive/package (launcher/Bridge pipeline) is required, and no
    authoring path is Python-reachable.

  1. probe_metahuman_surface    - symbol inventory + availability classification
  2. metahuman_enums            - MetaHumanAssetType / QualityLevel values
  3. metahuman_factory_capability - factory constructibility + can_import probes
  4. list_metahuman_assets      - project scan for MH assets (class + name)
  5. metahuman_verify_rule_call - guarded rule-class call (exact error record)
  6. metahuman_identity_gap     - local record: what ships / what is closed
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from tools.unreal.unreal_bridge import UnrealBridge


class MetaHumanToolsGap:

    def __init__(self, bridge: UnrealBridge):
        self.bridge = bridge

    @staticmethod
    def _q(value: Any) -> str:
        return json.dumps(str(value))

    # 1. surface inventory ---------------------------------------------------
    def probe_metahuman_surface(self) -> Dict[str, Any]:
        """Inventory every MetaHuman symbol + classify class/enum/other."""
        return self.bridge.execute_python(
            f"""
import unreal
names = sorted(n for n in dir(unreal) if "MetaHuman" in n)
rows = []
for n in names:
    o = getattr(unreal, n)
    if isinstance(o, type):
            try:
                doc = (o.__doc__ or "")[:400].replace(chr(10), " ")
            except Exception:
                doc = ""
            module = "MetaHumanSDKRuntime" if "MetaHumanSDKRuntime" in doc else (
                "MetaHumanSDKEditor" if "MetaHumanSDKEditor" in doc else "other")
            rows.append({{"name": n, "kind": "class", "module": module, "doc": doc[:220]}})
    __bridge_result__ = {{"ok": True, "total": len(rows), "symbols": rows}}
"""
        )

    # 2. enum surfaces -------------------------------------------------------
    def metahuman_enums(self) -> Dict[str, Any]:
        return self.bridge.execute_python(
            """
import unreal
out = {}
for en in ("MetaHumanAssetType", "MetaHumanQualityLevel"):
    e = getattr(unreal, en, None)
    if e is None:
        out[en] = {"present": False}
        continue
    try:
        vals = [v for v in dir(e) if v.isupper()]
        out[en] = {"present": True, "values": vals}
    except Exception as exc:
        out[en] = {"present": False, "error": str(exc)[:150]}
__bridge_result__ = {"ok": True, **out}
"""
        )

    # 3. factory capability --------------------------------------------------
    def metahuman_factory_capability(self) -> Dict[str, Any]:
        return self.bridge.execute_python(
            """
import unreal
out = {"constructible": False}
try:
    f = unreal.MetaHumanPackageFactory()
    out["constructible"] = True
    out["class_name"] = f.get_class().get_name()
    sc = f.get_editor_property("supported_class")
    out["supported_class"] = str(sc)
    out["can_import_empty"] = f.script_factory_can_import("")
    out["can_import_mhasset"] = f.script_factory_can_import("C:/nonexistent_metahuman.mhasset")
except Exception as exc:
    out["error"] = str(exc)[:250]
__bridge_result__ = {"ok": True, **out}
"""
        )

    # 4. project scan --------------------------------------------------------
    def list_metahuman_assets(self, root: str = "/Game") -> Dict[str, Any]:
        return self.bridge.execute_python(
            f"""
import unreal
allp = unreal.EditorAssetLibrary.list_assets({self._q(root)}, recursive=True, include_folder=False)
mh_names = []
identity = []
reg = unreal.AssetRegistryHelpers.get_asset_registry()
for p in allp:
    low = p.lower()
    if "metahuman" in low or "mh_" in low or low.endswith("_mh") or "/mh/" in low:
        mh_names.append(p)
    try:
        d = reg.get_asset_by_object_path(p + "." + p.rsplit("/", 1)[-1])
        if d.is_valid():
            cls = d.asset_class
            if cls == "MetaHumanIdentity" or "MetaHuman" in cls:
                identity.append({{"path": p, "class": cls}})
    except Exception:
        pass
__bridge_result__ = {{"ok": True, "total_assets": len(allp),
                       "metahuman_named": mh_names[:40], "mh_count": len(mh_names),
                       "metahuman_classed": identity[:40], "identity_count": len(identity)}}
"""
        )

    # 5. verify-rule call attempt (exact closed-surface evidence) ------------
    def metahuman_verify_rule_call(self, package_path: str) -> Dict[str, Any]:
        return self.bridge.execute_python(
            f"""
import unreal
try:
    v = unreal.VerifyMetaHumanPackageSource({self._q(package_path)})
    __bridge_result__ = {{"ok": True, "returned": str(v)[:150]}}
except Exception as exc:
    __bridge_result__ = {{"ok": False, "ok_false_is_expected": True,
                          "error_type": type(exc).__name__,
                          "error": str(exc)[:300]}}
"""
        )

    # 6. local gap record (pure python, engine root from disk) ----------------
    @staticmethod
    def metahuman_identity_gap(engine_root: Optional[str] = None) -> Dict[str, Any]:
        record: Dict[str, Any] = {
            "mirrored_in_session": "MetaHumanSDK only (26 symbols: runtime components, "
            "options structs, enums, package factory, verify rule classes)",
            "closed": [
                "MetaHumanIdentity asset authoring/import - implemented in C++ module "
                "MetaHumanAnimator/MetaHumanIdentityEditor, not Python-mirrored and not "
                "enabled in ASSET_Showcase2",
                "VerifyMetaHuman* helpers are rule classes - not string-callable; "
                "package-path invocation raises a nativize TypeError (captured)",
                "No Python path to acquire MetaHuman content - the launcher/Bridge "
                "pipeline produces the package that the SDK factory imports",
            ],
            "unblock": "enable MetaHumanAnimator + add C++ bridge UFUNCTION wrappers "
            "(or obtain a MetaHuman package via the launcher/Bridge pipeline)",
        }
        if engine_root:
            mh = os.path.join(engine_root, "Engine", "Plugins", "MetaHuman")
            record["engine_root_checked"] = engine_root
            record["plugins_on_disk"] = sorted(
                d for d in os.listdir(mh) if os.path.isdir(os.path.join(mh, d))
            ) if os.path.isdir(mh) else []
            sdk = os.path.join(mh, "MetaHumanSDK")
            record["metahuman_sdk_uplugin_present"] = os.path.isfile(
                os.path.join(sdk, "MetaHumanSDK.uplugin")
            )
            record["identity_module_on_disk"] = os.path.isdir(
                os.path.join(
                    mh, "MetaHumanAnimator", "Source", "MetaHumanIdentityEditor"
                )
            )
        return record
