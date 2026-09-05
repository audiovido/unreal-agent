"""aivido_update.py — portable Aivido runtime updater (cross-platform Python 3).

Consumes the PUBLIC GitHub release (canonical main -> releases/latest) as the
source of truth — never machine-to-machine copies. It:

  1. detects the locally installed version (ui/ui-version.json)
  2. queries the public latest release (raw canonical ui-version.json)
  3. compares AIVIDO_VERSION / UI_VERSION / BUILD_ID / content hash
  4. downloads the correct verified package from releases/latest
  5. verifies every file SHA-256 against the package manifest
  6. backs up the current release (rollback point)
  7. installs atomically (copy-only; unrelated files preserved)
  8. verifies local health
  9. rolls back on any failed local update

Only ui/ is ever written. Config, projects, and user data are never touched.

Usage:
  python scripts/aivido_update.py status                  # local vs public latest
  python scripts/aivido_update.py check                   # exit 0 = current, 2 = update available
  python scripts/aivido_update.py update [--ui-dir DIR] [--dry-run]
  python scripts/aivido_update.py register --name X [--type local|ssh] [--host H] [--user U] [--ui-dir D]
  python scripts/aivido_update.py list
"""
from __future__ import annotations

import argparse
import socket
import sys
from pathlib import Path
from typing import Optional, Sequence

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ui_release as ur  # noqa: E402


def _cfg() -> dict:
    return ur.load_config(ROOT / "config" / "ui_release.json")


def _ui_dir(override: Optional[str]) -> Path:
    return Path(override) if override else ROOT / _cfg().get("canonical_ui_dir", "ui")


def cmd_status(args: argparse.Namespace) -> int:
    cfg = _cfg()
    ui_dir = _ui_dir(args.ui_dir)
    has_update, local, pub = ur.update_check(cfg, ui_dir)
    print("MACHINE:", socket.gethostname())
    if local:
        print(f"LOCAL VERSION:   Aivido {local.get('aivido_version', '—')} · UI {local.get('ui_version', '—')} · "
              f"build {local.get('build_id', '—')} · hash {str(local.get('content_hash', ''))[:12]}…")
    else:
        print("LOCAL VERSION:   not installed (no ui/ui-version.json)")
    if pub:
        print(f"LATEST VERSION:  Aivido {pub.get('aivido_version', '—')} · UI {pub.get('ui_version', '—')} · "
              f"build {pub.get('build_id', '—')} · hash {str(pub.get('content_hash', ''))[:12]}…")
    else:
        print("LATEST VERSION:  public source unreachable / not published yet")
    state = "UPDATE AVAILABLE" if has_update else ("CURRENT" if pub else "UNKNOWN")
    print(f"UPDATE STATUS:   {state}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    cfg = _cfg()
    has_update, _, pub = ur.update_check(cfg, _ui_dir(args.ui_dir))
    if pub is None:
        print("public latest unreachable — cannot check (offline or not published)")
        return 1
    if has_update:
        print("update available")
        return 2
    print("current")
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    cfg = _cfg()
    ui_dir = _ui_dir(args.ui_dir)
    backup_root = Path(args.backup_root) if args.backup_root else ROOT / cfg.get("backup_root", "backup/ui")
    ok, detail = ur.update_runtime_install(cfg, ui_dir, backup_root, dry_run=args.dry_run)
    print(("[ui_release] UPDATE DRY-RUN: " if args.dry_run else "[ui_release] UPDATE: ") + detail)
    return 0 if ok else 1


def cmd_register(args: argparse.Namespace) -> int:
    inst = {"name": args.name, "type": args.type, "host": args.host or "",
            "user": args.user or "", "ui_dir": args.ui_dir or ""}
    installs = [i for i in ur.load_installations() if i.get("name") != args.name]
    installs.append(inst)
    ur.save_installations(installs)
    print(f"[ui_release] registered installation '{args.name}' ({args.type})")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    for i in ur.load_installations():
        print(f"  {i.get('name', '?')}  {i.get('type', '?')}  host={i.get('host') or '—'} "
              f"user={i.get('user') or '—'} ui_dir={i.get('ui_dir') or '—'}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="aivido_update.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status", help="local vs public latest")
    p.add_argument("--ui-dir", default=None)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("check", help="exit 0=current, 2=update available")
    p.add_argument("--ui-dir", default=None)
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("update", help="download + verify + backup + install + health-check")
    p.add_argument("--ui-dir", default=None)
    p.add_argument("--backup-root", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("register", help="register a runtime installation")
    p.add_argument("--name", required=True)
    p.add_argument("--type", choices=["local", "ssh"], default="local")
    p.add_argument("--host", default=None)
    p.add_argument("--user", default=None)
    p.add_argument("--ui-dir", default=None)
    p.set_defaults(func=cmd_register)

    p = sub.add_parser("list", help="list registered installations")
    p.set_defaults(func=cmd_list)

    args = ap.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except SystemExit as exc:
        code = exc.code
        if isinstance(code, str):
            print(f"[ui_release] {code}", file=sys.stderr)
            return 1
        return int(code or 1)
    except Exception as exc:  # noqa: BLE001
        print(f"[ui_release] ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))