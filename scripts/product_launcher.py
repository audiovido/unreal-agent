"""product_launcher.py — deterministic Unreal Agent product entrypoint.

Normal-user story: start the product (double-click / one command) and it
self-checks, refuses duplicates, starts the backend, and reports
readiness.  No PowerShell, no manual port entry.

Commands (all offline-safe except `serve`/`start`, which only manage the
local HTTP backend):

    product_launcher.py                 -> serve (default)
    product_launcher.py doctor          -> environment diagnostics
    product_launcher.py status          -> backend + lease status
    product_launcher.py start           -> start backend (bounded retries)
    product_launcher.py stop            -> stop backend
    product_launcher.py restart         -> stop then start
    product_launcher.py leases          -> show editor leases
    product_launcher.py first-run       -> first-run state snapshot
    product_launcher.py version         -> version metadata
    product_launcher.py selfcheck       -> import + smoke self-check

Exit codes: 0 = success/healthy, 1 = failure.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import app_config, editor_lease, env_doctor, first_run, \
    service_lifecycle  # noqa: E402

APP_TARGET = "app.product_app:app"
HEALTH_PATH = "/api/ua/status"
SERVICE_NAME = "unreal-agent-product"


def _cfg(args: argparse.Namespace) -> app_config.ProductConfig:
    cfg = app_config.load_config()
    if getattr(args, "port", None):
        cfg.backend_port = int(args.port)
        cfg.backend_url = f"http://{cfg.backend_host}:{cfg.backend_port}"
    return cfg


def cmd_doctor(args: argparse.Namespace) -> int:
    report = env_doctor.run(probe_backend=not args.no_probe)
    print(f"[doctor] {report['overall']} — {report['summary']}")
    print(report["user_error"])
    if args.verbose:
        print(env_doctor.developer_diagnostic(report))
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    return 0 if report["overall"] != "FAIL" else 1


def cmd_status(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    st = service_lifecycle.service_status(
        SERVICE_NAME, cfg.backend_host, cfg.backend_port,
        health_path=HEALTH_PATH, app_target=APP_TARGET)
    print(f"[status] backend: {st['state']} "
          f"(pid={st['pid']}, ready={st['ready']})")
    reg = editor_lease.LeaseRegistry()
    leases = reg.list_leases()
    if leases:
        for le in leases:
            print(f"[lease] {le.get('identity')} owner={le.get('owner_id')} "
                  f"task={le.get('task_id')} expires_at={le.get('expires_at')}")
    else:
        print("[lease] no editor leases held")
    return 0 if st["ready"] else 1


def cmd_start(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    res = service_lifecycle.ensure_running(
        SERVICE_NAME, cfg.backend_host, cfg.backend_port, APP_TARGET,
        health_path=HEALTH_PATH, max_attempts=args.retries,
        log_suffix="product")
    if res.get("ok"):
        print(f"[start] backend ready on {cfg.backend_url} "
              f"(attempt {res.get('attempts')}, pid {res.get('pid')})")
        return 0
    print(f"[start] FAILED: {res.get('error')}")
    for h in res.get("history", []):
        print(f"  attempt {h.get('attempt')}: "
              f"{'ok' if h.get('ok') else 'failed'} "
              f"{h.get('error', '')}")
    return 1


def cmd_stop(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    res = service_lifecycle.stop_service(SERVICE_NAME, cfg.backend_host,
                                         cfg.backend_port)
    print(f"[stop] {'stopped' if res.get('ok') else 'error: ' + str(res.get('error'))}")
    return 0 if res.get("ok") else 1


def cmd_restart(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    service_lifecycle.stop_service(SERVICE_NAME, cfg.backend_host,
                                   cfg.backend_port)
    return cmd_start(args)


def cmd_leases(args: argparse.Namespace) -> int:
    reg = editor_lease.LeaseRegistry(
        lease_dir=Path(args.lease_dir) if args.lease_dir else None)
    if args.force_release:
        out = reg.force_release(args.force_release, reason="cli force")
        print(json.dumps(out, indent=2, default=str))
        return 0
    print(json.dumps(reg.list_leases(), indent=2, default=str))
    return 0


def cmd_first_run(args: argparse.Namespace) -> int:
    doctor = env_doctor.run(probe_backend=not args.no_probe)
    cfg = _cfg(args)
    builds = app_config.detect_unreal_builds()
    usable = next((b for b in builds if b.get("editor_exe")), None)
    snap = first_run.build_progression(
        doctor=doctor, recent_project=cfg.recent_project,
        unreal_build=usable,
        file_path=Path(first_run.app_config.FIRST_RUN_FILE))
    print(json.dumps(snap, indent=2, default=str))
    return 0


def cmd_version(args: argparse.Namespace) -> int:
    print(json.dumps({
        "product": app_config.PRODUCT_NAME,
        "version": app_config.VERSION,
        "python": sys.version.split()[0],
    }, indent=2))
    return 0


def cmd_selfcheck(args: argparse.Namespace) -> int:
    ok = True
    for mod in ("app_config", "env_doctor", "service_lifecycle",
                "editor_lease", "first_run"):
        try:
            __import__(f"core.{mod}")
            print(f"[selfcheck] core.{mod} ok")
        except Exception as exc:
            ok = False
            print(f"[selfcheck] core.{mod} FAILED: {exc}")
    try:
        __import__("app.product_app")
        print("[selfcheck] app.product_app importable")
    except Exception as exc:
        ok = False
        print(f"[selfcheck] app.product_app import FAILED: {exc}")
    return 0 if ok else 1


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="product_launcher",
        description="Unreal Agent product launcher (Lane B).")
    p.add_argument("command", nargs="?", default="serve",
                   choices=["serve", "doctor", "status", "start", "stop",
                            "restart", "leases", "first-run", "version",
                            "selfcheck"])
    p.add_argument("--port", type=int, default=None,
                   help="backend port override (default from config)")
    p.add_argument("--retries", type=int, default=3)
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-probe", action="store_true",
                   help="skip live backend/port probes (offline doctor)")
    p.add_argument("--lease-dir", default=None)
    p.add_argument("--force-release", default=None,
                   help="lease identity to force-release")
    args = p.parse_args(argv)

    if args.command == "doctor":
        return cmd_doctor(args)
    if args.command == "status":
        return cmd_status(args)
    if args.command == "start":
        return cmd_start(args)
    if args.command == "stop":
        return cmd_stop(args)
    if args.command == "restart":
        return cmd_restart(args)
    if args.command == "leases":
        return cmd_leases(args)
    if args.command == "first-run":
        return cmd_first_run(args)
    if args.command == "version":
        return cmd_version(args)
    if args.command == "selfcheck":
        return cmd_selfcheck(args)
    # default: serve = start + report
    return cmd_start(args)


if __name__ == "__main__":
    sys.exit(main())
