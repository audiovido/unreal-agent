"""Smoke test for the reproducible package layout (Part 7).

Builds the layout into a temp dir and executes the packaged launcher
against the repo .venv python.  Never touches the live Unreal scene.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "bp_build", Path(__file__).resolve().parents[1]
    / "scripts" / "build_product_package.py")
bp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bp)


@pytest.fixture()
def pkg(tmp_path):
    report = bp.build(tmp_path / "dist")
    return Path(report["output_dir"]), report


def _run(pkg_dir: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "product_launcher.py", *args],
        cwd=str(pkg_dir), capture_output=True, text=True, timeout=90)


def test_layout_contents(pkg):
    pkg_dir, report = pkg
    for rel in ("product_launcher.py", "version.json", "manifest.json",
                "README-packaging.txt", "core/app_config.py",
                "core/product_core.py", "app/product_app.py",
                "app/__init__.py", "ui/product.html",
                "config/settings.json"):
        assert (pkg_dir / rel).exists(), rel
    assert report["ok"] is True
    assert pkg_dir.name.startswith("unreal-agent-")


def test_packaged_launcher_version(pkg):
    pkg_dir, _ = pkg
    r = _run(pkg_dir, "version")
    assert r.returncode == 0
    assert "0.1.0" in r.stdout


def test_packaged_launcher_doctor_offline(pkg):
    pkg_dir, _ = pkg
    r = _run(pkg_dir, "doctor", "--no-probe")
    # a hermetic box has no FAILs (unreal build detection is only a WARNING)
    assert r.returncode == 0
    assert "[doctor]" in r.stdout


def test_packaged_launcher_selfcheck(pkg):
    pkg_dir, _ = pkg
    r = _run(pkg_dir, "selfcheck")
    assert r.returncode == 0
    assert "app.product_app importable" in r.stdout


def test_packaged_leases_cli(pkg):
    pkg_dir, _ = pkg
    r = _run(pkg_dir, "leases", "--lease-dir", str(pkg_dir / "config" / "leases"))
    assert r.returncode == 0


def test_build_report_records_packager_evidence(pkg):
    _, report = pkg
    assert "native_exe" in report
    assert isinstance(report["native_exe"]["available"], bool)
    assert bool(report["native_exe"]["evidence"])
