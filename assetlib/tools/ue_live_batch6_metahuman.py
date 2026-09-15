"""BATCH 6 live validation: MetaHuman surface (bridge 6766, ASSET_Showcase2).

Probe-first batch: the running 5.8 session mirrors the MetaHumanSDK plugin only
(26 symbols); MetaHumanIdentity authoring lives in the un-enabled
MetaHumanAnimator/MetaHumanIdentityEditor C++ module. These steps prove every
substantiable primitive live and record the closed creation surface with the
exact engine error text. Run:  python assetlib/tools/ue_live_batch6_metahuman.py
"""
import json
import os
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools", "unreal"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from unreal_bridge import UnrealBridge  # noqa: E402
from metahuman_tools_gap import MetaHumanToolsGap  # noqa: E402

BRIDGE = ("127.0.0.1", 6766)
ENGINE_ROOT = "D:/Program Files/Epic Games/UE_5.8"
REPORT = os.path.join(
    os.path.dirname(__file__), "..", "reports", "metahuman_tools_batch6.json"
)


def main() -> int:
    bridge = UnrealBridge(*BRIDGE)
    mh = MetaHumanToolsGap(bridge)
    steps: List[Dict[str, Any]] = []

    def step(name: str, ok: bool, **detail: Any) -> None:
        steps.append({"step": name, "ok": bool(ok), **detail})
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")

    # 01 surface inventory ---------------------------------------------------
    res = mh.probe_metahuman_surface()
    body = res.get("result") or res
    syms = body.get("symbols", [])
    names = [s["name"] for s in syms]
    runtime = sum(1 for s in syms if s.get("module") == "MetaHumanSDKRuntime")
    step(
        "01_probe_surface",
        body.get("ok") is True and len(syms) >= 20,
        total=body.get("total"),
        runtime_module=runtime,
        editor_module=len(syms) - runtime,
        closed_classes_present={
            c: c in names
            for c in ("MetaHumanIdentity", "MetaHumanPreset", "MetaHumanComponent")
        },
    )

    # 02 enums ---------------------------------------------------------------
    res = mh.metahuman_enums()
    body = res.get("result") or res
    at = body.get("MetaHumanAssetType", {})
    ql = body.get("MetaHumanQualityLevel", {})
    step(
        "02_enums",
        at.get("present") is True and ql.get("present") is True
        and "CHARACTER" in at.get("values", []) and "GROOM" in at.get("values", [])
        and "CINEMATIC" in ql.get("values", []),
        asset_types=at.get("values"),
        quality_levels=ql.get("values"),
    )

    # 03 factory capability --------------------------------------------------
    res = mh.metahuman_factory_capability()
    body = res.get("result") or res
    step(
        "03_factory_capability",
        body.get("ok") is True and body.get("constructible") is True
        and body.get("can_import_empty") is False
        and body.get("can_import_mhasset") is False,
        supported_class=body.get("supported_class"),
        can_import_empty=body.get("can_import_empty"),
        can_import_mhasset=body.get("can_import_mhasset"),
    )

    # 04 project scan --------------------------------------------------------
    res = mh.list_metahuman_assets("/Game")
    body = res.get("result") or res
    step(
        "04_project_scan",
        body.get("ok") is True and isinstance(body.get("total_assets"), int)
        and body.get("identity_count") == 0,
        total_assets=body.get("total_assets"),
        mh_named=body.get("mh_count"),
        identity_assets=body.get("identity_count"),
    )

    # 05 verify-rule closed call (exact error text) ---------------------------
    res = mh.metahuman_verify_rule_call("/Game/Showcase/Fox/Fox")
    body = res.get("result") or res
    err = body.get("error", "")
    step(
        "05_verify_rule_call_closed",
        body.get("ok_false_is_expected") is True
        and "NativizeObject" in err,
        error_type=body.get("error_type"),
        error=err[:220],
    )

    # 06 gap record ----------------------------------------------------------
    gap = mh.metahuman_identity_gap(ENGINE_ROOT)
    step(
        "06_identity_gap_record",
        isinstance(gap.get("plugins_on_disk"), list)
        and "MetaHumanSDK" in gap.get("plugins_on_disk", [])
        and gap.get("identity_module_on_disk") is True,
        plugins_on_disk=gap.get("plugins_on_disk"),
        sdk_uplugin=gap.get("metahuman_sdk_uplugin_present"),
        identity_module_on_disk=gap.get("identity_module_on_disk"),
        unblock=gap.get("unblock"),
    )

    passed = sum(1 for s in steps if s["ok"])
    verdict = "PASS" if passed == len(steps) else "FAIL"
    report = {
        "batch": 6,
        "topic": "MetaHuman / identity surface (probe-first, honest-gap)",
        "bridge": "127.0.0.1:6766 ASSET_Showcase2",
        "verdict": verdict,
        "steps_total": len(steps),
        "steps_passed": passed,
        "steps": steps,
        "gap_record": gap,
        "note": (
            "MetaHumanSDK mirrored live (runtime components, enums, factory, "
            "verify rule classes); identity AUTHORING is closed - MetaHumanAnimator/"
            "MetaHumanIdentityEditor C++ module not enabled/mirrored. Exact error "
            "text recorded in step 05. No MH content present in project (step 04)."
        ),
    }
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w") as fh:
        json.dump(report, fh, indent=2)
    print(f"\nVERDICT: {verdict} ({passed}/{len(steps)}) -> {REPORT}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
