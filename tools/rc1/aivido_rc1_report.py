#!/usr/bin/env python3
"""AIVIDO RC1 Report Generator — produces concise human-readable report from gate JSON.

Usage:
    python tools/rc1/aivido_rc1_report.py <gate_json> [--out report.md]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aivido_rc1_gate import CHECK_DESCRIPTIONS


def format_report(gate_json: dict) -> str:
    """Generate concise human-readable markdown report."""
    lines = []
    verdict = gate_json.get("verdict", "UNKNOWN")
    at = gate_json.get("at", "unknown")

    lines.append(f"# AIVIDO RC1 Acceptance Report")
    lines.append("")
    lines.append(f"**Verdict: {verdict}**  ")
    lines.append(f"**Generated: {at}**  ")
    lines.append("")

    checks = gate_json.get("checks", {})
    reasons = gate_json.get("reasons", [])

    # Summary
    passed = sum(1 for c in checks.values() if c.get("ok"))
    total = len(checks)
    lines.append(f"## Summary: {passed}/{total} checks passed")
    lines.append("")

    # Individual checks
    lines.append("## Check Results")
    lines.append("")

    for check_id, detail in checks.items():
        ok = detail.get("ok", False)
        status = "✅ PASS" if ok else "❌ FAIL"
        desc = CHECK_DESCRIPTIONS.get(check_id, check_id)
        lines.append(f"### {status} — {desc}")
        if ok and detail:
            for k, v in detail.items():
                if k != "ok":
                    lines.append(f"- **{k}**: {v}")
        elif not ok:
            reason = detail.get("reason", "unknown")
            lines.append(f"- **Reason**: {reason}")
        lines.append("")

    # Failures summary
    if reasons:
        lines.append("## Failures")
        lines.append("")
        for r in reasons:
            lines.append(f"- {r}")
        lines.append("")

    # Machine-readable note
    lines.append("---")
    lines.append("")
    lines.append("*Machine-readable JSON available from gate `--json-out`.*")

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate human report from RC1 gate JSON")
    ap.add_argument("gate_json", help="Path to gate JSON output")
    ap.add_argument("--out", default="", help="Write report to file (default: stdout)")
    args = ap.parse_args()

    gate_path = Path(args.gate_json)
    if not gate_path.exists():
        print(f"Gate JSON not found: {gate_path}", file=sys.stderr)
        return 1

    try:
        data = json.loads(gate_path.read_text())
    except Exception as exc:
        print(f"Failed to parse gate JSON: {exc}", file=sys.stderr)
        return 1

    report = format_report(data)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report)
        print(f"Report written to {out_path}")
    else:
        print(report)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())