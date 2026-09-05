"""ui_release.py — Aivido canonical UI release tooling (cross-platform).

ONE canonical frontend source (ui/) -> deterministic build -> staging ->
user review -> exact approval phrase ("OK PUBLISH UI") -> the SAME build
deployed everywhere (Shadow local + Mac remote).

Cross-platform rule: pure Python 3 stdlib (pathlib, shutil, hashlib,
json, urllib; subprocess only for git/ssh/scp). No rsync, md5sum,
find -print0, xargs, WSL, or Git Bash-specific behavior. Works on
Windows Shadow and macOS.

Commands
--------
  manifest   Inventory the canonical ui/ directory (sha256 per file)
  build      Deterministic build -> dist/ui-builds/<build_id>/
  stage      Point staging at a build for review
  serve      Run the staging server (route parity + /api proxy)
  deploy     Promote a build to a target (default: shadow local)
  verify     Hash-parity verification of a build or a live target
  rollback   Restore a target from backup
  status     Current build / staging / backup state

Release gate: `deploy` never touches the live target unless the caller
explicitly runs it; the canonical flow is build -> stage -> review ->
"OK PUBLISH UI" -> deploy + verify.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "ui_release.json"
DEFAULT_BUILD_ROOT = ROOT / "dist" / "ui-builds"
DEFAULT_STAGING_ROOT = ROOT / "dist" / "ui-staging"
DEFAULT_BACKUP_ROOT = ROOT / "backup" / "ui"
DEFAULT_STAGING_PORT = 8890
DEFAULT_BACKEND = "http://127.0.0.1:8765"

# ui-version.json contract — exactly these fields (mission requirement).
VERSION_FIELDS = ("product", "ui_version", "build_id", "git_sha", "timestamp", "content_hash")

# Legacy/non-canonical content inside ui/ that must never be built or deployed.
# ui-version.json + build-manifest.json are release OUTPUTS — they are written
# into builds and deployed explicitly, never swept into the canonical inventory.
CANONICAL_EXCLUDE_NAMES = {"ui.zip", "index.html.broken-encoding", "ui-version.json", "build-manifest.json", "release-manifest.json"}
CANONICAL_EXCLUDE_DIRS = {"backup", "backup-20260820-081408"}

# Cache-busting: rewrite /static/<name>?v=<old> to ?v=<sha8 of file> in HTML,
# and url(/static/<name>) in CSS.
HTML_REF_RE = re.compile(r"(?P<pre>(?:src|href)=[\"']/static/)(?P<name>[^\"'?#]+)(?:\?v=[A-Za-z0-9._-]+)?(?P<post>[\"'])")
CSS_REF_RE = re.compile(r"(?P<pre>url\([\"']?/static/)(?P<name>[^\"'?#()]+)(?:\?v=[A-Za-z0-9._-]+)?(?P<post>[\"']?\))")

# Route map mirrored by the backend (app/api.py) and the staging server.
ROUTES = {
    "": "ava.html",        # product UI — living AI companion
    "app": "aivido.html",  # Director's Booth
    "dev": "index.html",   # developer console
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 256), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha8(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- git ----
def git_info(repo_root: Path) -> Tuple[str, bool]:
    """Return (short_sha, dirty). Never raises; falls back to unknown."""
    sha, dirty = "unknown", False
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--short=12", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0:
            sha = out.stdout.strip() or "unknown"
        st = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain"],
            capture_output=True, text=True, timeout=10,
        )
        dirty = st.returncode == 0 and bool(st.stdout.strip())
    except Exception:
        pass
    return sha, dirty


# ------------------------------------------------------------- config ----
def default_config() -> Dict[str, Any]:
    return {
        "product": "Aivido",
        "product_label": "Unreal Agent — Ava · living AI companion",
        "aivido_version": "0.1.0",
        "ui_version": "1.0.0",
        "canonical_ui_dir": "ui",
        "build_root": "dist/ui-builds",
        "staging": {"dir": "dist/ui-staging", "port": DEFAULT_STAGING_PORT, "backend": DEFAULT_BACKEND},
        "backup_root": "backup/ui",
        "release": {
            "github_repo": "",
            "github_branch": "main",
            "public_base": "",
            "latest_url": "",
            "raw_ui_version_url": "",
            "commit_paths": ["ui", "scripts/ui_release.py", "scripts/ui_staging_server.py",
                             "config/ui_release.json", "tests/test_ui_release.py"],
            "release_root": "dist/ui-releases",
            "package_root": "dist/releases",
            "update_check_enabled": True,
        },
        "targets": {
            "shadow": {"type": "local", "ui_dir": "ui", "base_url": "http://127.0.0.1:8765"},
            "mac": {
                "type": "ssh",
                "host": "",
                "user": "",
                "ui_dir": "",
                "base_url": "http://127.0.0.1:8765",
            },
        },
    }


def load_config(path: Optional[Path] = None) -> Dict[str, Any]:
    cfg = default_config()
    p = Path(path) if path else DEFAULT_CONFIG
    if p.is_file():
        try:
            loaded = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                cfg = _deep_merge(cfg, loaded)
        except Exception as exc:  # never die on a broken config
            print(f"[ui_release] WARNING: could not read {p}: {exc}")
    return cfg


def _deep_merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


# ------------------------------------------------------------ inventory ---
def canonical_files(ui_dir: Path) -> List[Path]:
    """Canonical UI files: everything in ui/ except legacy zip/backup junk."""
    if not ui_dir.is_dir():
        raise FileNotFoundError(f"canonical UI dir not found: {ui_dir}")
    files: List[Path] = []
    for p in sorted(ui_dir.iterdir()):
        if p.is_dir():
            if p.name in CANONICAL_EXCLUDE_DIRS or p.name.startswith("backup"):
                continue
            files.extend(canonical_files(p))
        else:
            if p.name in CANONICAL_EXCLUDE_NAMES or p.suffix.lower() not in (".html", ".css", ".js", ".json", ".svg", ".png", ".ico", ".woff2", ".txt"):
                continue
            files.append(p)
    return sorted(files)


def inventory(ui_dir: Path) -> Dict[str, str]:
    """relpath -> sha256 for every canonical file."""
    return {str(p.relative_to(ui_dir)).replace("\\", "/"): sha256_file(p) for p in canonical_files(ui_dir)}


def compute_content_hash(file_hashes: Dict[str, str]) -> str:
    """Deterministic content hash over canonical UI file contents.

    Independent of timestamp/build_id so identical sources produce the
    identical hash on Shadow and Mac (parity test material).
    """
    parts = sorted(f"{rel}\0{sha}" for rel, sha in file_hashes.items())
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


# ---------------------------------------------------------- cache bust ----
def rewrite_cache_bust(text: str, build_dir: Path) -> str:
    """Rewrite /static/<name>?v=... references to ?v=<sha8 of that file>.

    References to files missing from the build are left untouched so a
    broken reference can never be introduced by the build.
    """

    def _sub(m: "re.Match[str]") -> str:
        name = m.group("name")
        target = build_dir / name
        if not target.is_file():
            return m.group(0)
        return f'{m.group("pre")}{name}?v={sha8(target.read_text(encoding="utf-8"))}{m.group("post")}'

    return HTML_REF_RE.sub(_sub, text)


def rewrite_cache_bust_css(text: str, build_dir: Path) -> str:
    def _sub(m: "re.Match[str]") -> str:
        name = m.group("name")
        target = build_dir / name
        if not target.is_file():
            return m.group(0)
        return f'{m.group("pre")}{name}?v={sha8(target.read_text(encoding="utf-8"))}{m.group("post")}'

    return CSS_REF_RE.sub(_sub, text)


# ---------------------------------------------------------------- build ---
def build(
    ui_dir: Path,
    out_root: Path,
    *,
    product: str = "Aivido",
    aivido_version: str = "0.1.0",
    ui_version: str = "1.0.0",
    build_id: Optional[str] = None,
    git_sha: Optional[str] = None,
    git_dirty: Optional[bool] = None,
    timestamp: Optional[str] = None,
    quiet: bool = False,
) -> Dict[str, Any]:
    """Deterministic canonical build -> out_root/<build_id>/."""
    file_hashes = inventory(ui_dir)
    content_hash = compute_content_hash(file_hashes)
    build_id = build_id or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    ts = timestamp or utc_now()
    if git_sha is None or git_dirty is None:
        gsha, gdirty = git_info(ROOT)
        git_sha = git_sha if git_sha is not None else gsha
        git_dirty = git_dirty if git_dirty is not None else gdirty

    build_dir = out_root / build_id
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)

    # Pass 1: copy every canonical file verbatim (byte-for-byte).
    for rel in file_hashes:
        src = ui_dir / rel
        dst = build_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    # Pass 2: rewrite cache-busting refs in place — every referenced file is
    # now present, so no /static/<file> reference is ever skipped.
    for rel in file_hashes:
        if not rel.endswith((".html", ".css")):
            continue
        path = build_dir / rel
        text = path.read_text(encoding="utf-8", errors="replace")
        if rel.endswith(".html"):
            text = rewrite_cache_bust(text, build_dir)
        else:
            text = rewrite_cache_bust_css(text, build_dir)
        path.write_text(text, encoding="utf-8")

    # Record hashes of the BUILT (deployed) files in the manifest so served-
    # byte parity checks compare against exactly what ships.
    built_hashes = {rel: sha256_file(build_dir / rel) for rel in file_hashes}

    version = {
        "product": product,
        "aivido_version": aivido_version,
        "ui_version": ui_version,
        "build_id": build_id,
        "git_sha": git_sha,
        "timestamp": ts,
        "content_hash": content_hash,
    }
    (build_dir / "ui-version.json").write_text(
        json.dumps(version, indent=2) + "\n", encoding="utf-8")

    manifest = {
        "build_id": build_id,
        "aivido_version": aivido_version,
        "ui_version": ui_version,
        "product": product,
        "git_sha": git_sha,
        "git_dirty": git_dirty,
        "timestamp": ts,
        "content_hash": content_hash,
        "routes": ROUTES,
        "files": built_hashes,
    }
    (build_dir / "build-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    if not quiet:
        print(f"[ui_release] build complete:  {build_dir}")
        print(f"  build_id      {build_id}")
        print(f"  ui_version    {ui_version}")
        print(f"  git_sha       {git_sha}{' (dirty)' if git_dirty else ''}")
        print(f"  content_hash  {content_hash}")
        print(f"  files         {len(file_hashes)} canonical files")
    return {"build_id": build_id, "build_dir": str(build_dir), "content_hash": content_hash,
            "version": version, "manifest": manifest}


# --------------------------------------------------------------- stage ----
def stage(out_root: Path, staging_root: Path, build_id: str, *, quiet: bool = False) -> Path:
    build_dir = out_root / build_id
    if not (build_dir / "build-manifest.json").is_file():
        raise FileNotFoundError(f"build not found: {build_dir} (run 'ui_release.py build' first)")
    staging_root.mkdir(parents=True, exist_ok=True)
    (staging_root / "current.txt").write_text(build_id + "\n", encoding="utf-8")
    manifest = json.loads((build_dir / "build-manifest.json").read_text(encoding="utf-8"))
    record = {
        "build_id": build_id,
        "ui_version": manifest["ui_version"],
        "product": manifest["product"],
        "git_sha": manifest["git_sha"],
        "content_hash": manifest["content_hash"],
        "build_dir": str(build_dir),
        "routes": ROUTES,
    }
    (staging_root / "staging.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    if not quiet:
        print(f"[ui_release] staged build '{build_id}' for review")
        print(f"  staging dir   {staging_root}")
        print(f"  staging URL   http://127.0.0.1:{DEFAULT_STAGING_PORT}/  (run 'serve')")
    return staging_root


def current_staged_build(staging_root: Path) -> Optional[str]:
    f = staging_root / "current.txt"
    if f.is_file():
        return f.read_text(encoding="utf-8").strip() or None
    return None


# --------------------------------------------------------------- deploy ---
def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def deploy_build(
    build_dir: Path,
    ui_dir: Path,
    backup_root: Path,
    *,
    dry_run: bool = False,
    record_id: Optional[str] = None,
    quiet: bool = False,
) -> Dict[str, Any]:
    """Promote a build into a target ui dir with a restorable backup.

    Copy-only semantics: unrelated files in the target dir are never
    deleted. Every overwritten file is snapshotted under
    backup_root/<record_id>/ with its sha256, plus the deployed build's
    manifest, so rollback is exact.
    """
    manifest = json.loads((build_dir / "build-manifest.json").read_text(encoding="utf-8"))
    record_id = record_id or manifest["build_id"]
    deployed_files = list(manifest["files"].keys()) + ["ui-version.json", "build-manifest.json"]

    if not ui_dir.is_dir():
        raise FileNotFoundError(f"target ui dir not found: {ui_dir}")

    backup_dir = backup_root / record_id
    backed_up: Dict[str, str] = {}
    for rel in deployed_files:
        existing = ui_dir / rel
        if existing.is_file():
            backed_up[rel] = sha256_file(existing)

    actions = [f"backup {len(backed_up)} existing files -> {backup_dir}",
               f"copy {len(deployed_files)} build files -> {ui_dir}",
               "delete nothing (copy-only deploy)"]
    if dry_run:
        if not quiet:
            print("[ui_release] DEPLOY DRY-RUN — no changes written")
            for a in actions:
                print(f"  would {a}")
        return {"dry_run": True, "record_id": record_id, "backed_up": backed_up}

    # 1) backup
    backup_dir.mkdir(parents=True, exist_ok=True)
    for rel, _ in backed_up.items():
        _copy_file(ui_dir / rel, backup_dir / rel)
    record = {
        "record_id": record_id,
        "build_id": manifest["build_id"],
        "ui_version": manifest["ui_version"],
        "content_hash": manifest["content_hash"],
        "deployed_at": utc_now(),
        "backed_up": backed_up,
        "deployed": deployed_files,
    }
    (backup_dir / "deploy-record.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    _copy_file(build_dir / "build-manifest.json", backup_dir / "build-manifest.json")

    # 2) copy build -> target
    for rel in deployed_files:
        _copy_file(build_dir / rel, ui_dir / rel)

    # 3) verify what we just wrote
    mismatches = []
    for rel in deployed_files:
        served = ui_dir / rel
        if not served.is_file():
            mismatches.append(f"{rel}: missing")
            continue
        expected = sha256_file(build_dir / rel)
        if sha256_file(served) != expected:
            mismatches.append(f"{rel}: hash mismatch")
    if mismatches:
        raise RuntimeError("post-deploy verification failed: " + "; ".join(mismatches))

    if not quiet:
        print(f"[ui_release] deployed build '{manifest['build_id']}' -> {ui_dir}")
        print(f"  backup        {backup_dir}")
        print(f"  files         {len(deployed_files)} (copy-only; nothing deleted)")
        print(f"  verified      all {len(deployed_files)} files hash-match the build")
    return {"dry_run": False, "record_id": record_id, "backed_up": backed_up, "deployed": deployed_files}


def latest_backup(backup_root: Path) -> Optional[Path]:
    if not backup_root.is_dir():
        return None
    cands = [p for p in backup_root.iterdir()
             if p.is_dir() and (p / "deploy-record.json").is_file()]
    if not cands:
        return None
    return max(cands, key=lambda p: p.stat().st_mtime)


def rollback(ui_dir: Path, backup_root: Path, build_id: Optional[str] = None,
             *, dry_run: bool = False, quiet: bool = False) -> Dict[str, Any]:
    """Restore a target ui dir from a deploy record (exact inverse)."""
    if build_id:
        backup_dir = backup_root / build_id
        if not (backup_dir / "deploy-record.json").is_file():
            raise FileNotFoundError(f"no deploy record for {build_id} under {backup_root}")
    else:
        backup_dir = latest_backup(backup_root)
        if backup_dir is None:
            raise FileNotFoundError(f"no deploy backups under {backup_root}")
    record = json.loads((backup_dir / "deploy-record.json").read_text(encoding="utf-8"))
    backed_up = record.get("backed_up", {})
    deployed = record.get("deployed", [])
    to_remove = [rel for rel in deployed if rel not in backed_up]

    if dry_run:
        if not quiet:
            print(f"[ui_release] ROLLBACK DRY-RUN for record {record['record_id']}")
            print(f"  restore {len(backed_up)} files from {backup_dir}")
            print(f"  remove  {len(to_remove)} files that the deployed build introduced")
        return {"dry_run": True, "record_id": record["record_id"], "restore": list(backed_up), "remove": to_remove}

    restored = []
    for rel, expected in backed_up.items():
        src = backup_dir / rel
        if not src.is_file():
            raise RuntimeError(f"backup file missing for {rel} — refusing partial rollback")
        if sha256_file(src) != expected:
            raise RuntimeError(f"backup hash mismatch for {rel} — refusing rollback")
        _copy_file(src, ui_dir / rel)
        restored.append(rel)
    for rel in to_remove:
        gone = ui_dir / rel
        if gone.is_file():
            gone.unlink()

    # verify
    bad = [rel for rel in restored if sha256_file(ui_dir / rel) != backed_up[rel]]
    if bad:
        raise RuntimeError("rollback verification failed: " + "; ".join(bad))

    if not quiet:
        print(f"[ui_release] rolled back record {record['record_id']} (build {record.get('build_id')})")
        print(f"  restored {len(restored)} files, removed {len(to_remove)} build-only files")
        print(f"  verified  all restored files hash-match the backup")
    return {"dry_run": False, "record_id": record["record_id"], "restored": restored, "remove": to_remove}


# --------------------------------------------------------------- verify ---
def verify_build_local(build_dir: Path, *, quiet: bool = False) -> List[Dict[str, Any]]:
    """Check a build dir against its own build-manifest.json (offline parity)."""
    checks: List[Dict[str, Any]] = []
    manifest_path = build_dir / "build-manifest.json"
    if not manifest_path.is_file():
        return [{"name": "build-manifest.json", "ok": False, "detail": "missing"}]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    version_path = build_dir / "ui-version.json"
    if version_path.is_file():
        version = json.loads(version_path.read_text(encoding="utf-8"))
        missing = [f for f in VERSION_FIELDS if f not in version]
        checks.append({"name": "ui-version.json fields",
                       "ok": not missing,
                       "detail": "missing: " + ",".join(missing) if missing else "all 6 fields present"})
        if version.get("content_hash") == manifest.get("content_hash"):
            checks.append({"name": "content_hash (version==manifest)", "ok": True, "detail": version.get("content_hash", "")})
        else:
            checks.append({"name": "content_hash (version==manifest)", "ok": False,
                           "detail": f"version {version.get('content_hash')} != manifest {manifest.get('content_hash')}"})
    else:
        checks.append({"name": "ui-version.json", "ok": False, "detail": "missing"})

    expected = dict(manifest.get("files", {}))
    expected["ui-version.json"] = sha256_file(build_dir / "ui-version.json") if version_path.is_file() else None
    expected["build-manifest.json"] = sha256_file(manifest_path)
    bad = []
    for rel, want in sorted(expected.items()):
        if want is None:
            continue
        p = build_dir / rel
        if not p.is_file():
            bad.append(f"{rel}:missing")
        elif sha256_file(p) != want:
            bad.append(f"{rel}:hash")
    checks.append({"name": f"file hash parity ({len(expected)} files)",
                   "ok": not bad, "detail": "; ".join(bad) if bad else "all match"})

    # cache-busting applied in built HTML?
    for route, html_name in ROUTES.items():
        html_path = build_dir / html_name
        if not html_path.is_file():
            continue
        html = html_path.read_text(encoding="utf-8")
        refs = re.findall(r"/static/([A-Za-z0-9._/-]+)(\?v=[A-Za-z0-9]{8})?[\"']", html)
        unversioned = [n for n, v in refs if not v and (build_dir / n).is_file()]
        stale = [f"{n}:{v}" for n, v in refs
                 if v and sha8((build_dir / n).read_text(encoding="utf-8")) != v.lstrip("?v=")]
        ok = not unversioned and not stale and bool(refs)
        checks.append({"name": f"cache-bust {route or '/'} ({html_name})",
                       "ok": ok,
                       "detail": f"{len(refs)} refs" + (f", stale: {stale}" if stale else "") + (f", unversioned: {unversioned}" if unversioned else "")})
    if not quiet:
        for c in checks:
            print(f"  [{'PASS' if c['ok'] else 'FAIL'}] {c['name']}: {c['detail']}")
    return checks


def _http_get(url: str, timeout: float = 10.0) -> Tuple[int, bytes, Dict[str, str]]:
    req = urllib.request.Request(url, headers={"User-Agent": "ui_release_verify/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)
    except Exception as exc:  # noqa: BLE001 — report any transport failure as check detail
        raise RuntimeError(f"GET {url}: {exc}") from exc


def verify_target(base_urls: Sequence[str], build_dir: Optional[Path] = None,
                  *, timeout: float = 10.0, quiet: bool = False) -> List[Dict[str, Any]]:
    """Check live targets: routes serve, ui-version.json present, and (when a
    local build dir is given) every served asset hash-matches the build."""
    checks: List[Dict[str, Any]] = []
    expected = None
    if build_dir is not None and (build_dir / "build-manifest.json").is_file():
        expected = json.loads((build_dir / "build-manifest.json").read_text(encoding="utf-8"))

    served_versions = []
    for base in base_urls:
        base = base.rstrip("/")
        ok_all = True
        for route, html_name in ROUTES.items():
            url = f"{base}/{route}" if route else f"{base}/"
            try:
                status, body, _ = _http_get(url, timeout)
            except Exception as exc:
                checks.append({"name": f"{base} /{route}", "ok": False, "detail": str(exc)})
                ok_all = False
                continue
            if status != 200:
                checks.append({"name": f"{base} /{route}", "ok": False, "detail": f"HTTP {status}"})
                ok_all = False
                continue
            marker = f'<title>{expected.get("product", "Aivido")}' if expected else ""
            detail = f"HTTP 200, {len(body)} bytes"
            checks.append({"name": f"{base} /{route}", "ok": True, "detail": detail})

        # ui-version.json + asset parity
        try:
            status, body, _ = _http_get(f"{base}/static/ui-version.json", timeout)
        except Exception as exc:
            checks.append({"name": f"{base} /static/ui-version.json", "ok": False, "detail": str(exc)})
            continue
        if status != 200:
            checks.append({"name": f"{base} /static/ui-version.json", "ok": False, "detail": f"HTTP {status}"})
            continue
        try:
            served = json.loads(body.decode("utf-8"))
        except Exception:
            checks.append({"name": f"{base} /static/ui-version.json", "ok": False, "detail": "not JSON"})
            continue
        missing = [f for f in VERSION_FIELDS if f not in served]
        checks.append({"name": f"{base} ui-version.json", "ok": not missing,
                       "detail": (f"build {served.get('build_id')} v{served.get('ui_version')} "
                                  f"hash {served.get('content_hash', '')[:12]}…")
                       if not missing else "missing fields: " + ",".join(missing)})
        served_versions.append(served)

        if expected is not None and served.get("content_hash") == expected.get("content_hash") \
                and served.get("build_id") == expected.get("build_id"):
            checks.append({"name": f"{base} == local build parity", "ok": True,
                           "detail": f"build {expected['build_id']} matches"})
        elif expected is not None:
            checks.append({"name": f"{base} == local build parity", "ok": False,
                           "detail": f"served {served.get('build_id')} != local {expected.get('build_id')}"})

        # asset hash parity from served HTML refs
        if expected is not None:
            bad_assets = []
            checked = 0
            for route, html_name in ROUTES.items():
                url = f"{base}/{route}" if route else f"{base}/"
                try:
                    status, body, _ = _http_get(url, timeout)
                except Exception:
                    continue
                if status != 200:
                    continue
                html = body.decode("utf-8", errors="replace")
                for name in re.findall(r"/static/([A-Za-z0-9._/-]+)(?:\?v=[A-Za-z0-9]{8})?[\"']", html):
                    want = expected.get("files", {}).get(name)
                    if want is None:
                        continue
                    checked += 1
                    try:
                        status2, asset, _ = _http_get(f"{base}/static/{name}", timeout)
                    except Exception:
                        bad_assets.append(f"{name}:unreachable")
                        continue
                    if status2 != 200 or sha256_bytes(asset) != want:
                        bad_assets.append(f"{name}:hash")
            checks.append({"name": f"{base} asset hash parity",
                           "ok": not bad_assets,
                           "detail": f"{checked} assets match build" if not bad_assets else "; ".join(bad_assets[:6])})

    # cross-target parity
    if len(served_versions) >= 2:
        a, b = served_versions[0], served_versions[1]
        same = (a.get("content_hash") == b.get("content_hash") and a.get("build_id") == b.get("build_id"))
        checks.append({"name": "cross-target parity", "ok": same,
                       "detail": f"hash {a.get('content_hash', '')[:12]}… vs {b.get('content_hash', '')[:12]}… "
                                 f"build {a.get('build_id')} vs {b.get('build_id')}"})
    if not quiet:
        for c in checks:
            print(f"  [{'PASS' if c['ok'] else 'FAIL'}] {c['name']}: {c['detail']}")
    return checks


# ------------------------------------------------------------- status ----
def status_report(cfg: Dict[str, Any], *, quiet: bool = False) -> Dict[str, Any]:
    ui_dir = ROOT / cfg["canonical_ui_dir"]
    build_root = ROOT / cfg["build_root"]
    staging_root = ROOT / cfg["staging"]["dir"]
    backup_root = ROOT / cfg["backup_root"]
    report: Dict[str, Any] = {"ui_dir": str(ui_dir)}

    deployed = ui_dir / "ui-version.json"
    if deployed.is_file():
        try:
            report["deployed"] = json.loads(deployed.read_text(encoding="utf-8"))
        except Exception:
            report["deployed"] = {"error": "unparseable ui-version.json"}
    else:
        report["deployed"] = None

    report["staged_build"] = current_staged_build(staging_root)
    report["builds"] = sorted(
        [p.name for p in build_root.iterdir() if (p / "build-manifest.json").is_file()],
        reverse=True) if build_root.is_dir() else []
    report["backups"] = sorted(
        [p.name for p in backup_root.iterdir() if (p / "deploy-record.json").is_file()],
        reverse=True) if backup_root.is_dir() else []

    if not quiet:
        print(f"[ui_release] status")
        print(f"  canonical ui   {ui_dir}")
        print(f"  deployed       {report['deployed'].get('build_id', '— (none)') if report['deployed'] else '— (none)'} "
              f"(v{report['deployed'].get('ui_version') if report['deployed'] else '—'})")
        print(f"  staged         {report['staged_build'] or '— (none)'}")
        print(f"  builds         {', '.join(report['builds'][:5]) or '— (none)'}"
              + (f" (+{len(report['builds']) - 5} more)" if len(report['builds']) > 5 else ""))
        print(f"  backups        {', '.join(report['backups'][:5]) or '— (none)'}"
              + (f" (+{len(report['backups']) - 5} more)" if len(report['backups']) > 5 else ""))
        for name, t in cfg.get("targets", {}).items():
            ready = "READY" if (t.get("type") == "local" or (t.get("host") and t.get("ui_dir"))) else "NOT CONFIGURED"
            print(f"  target {name:<6} {t.get('type', '?'):<6} {t.get('ui_dir', '')}  [{ready}]")
        rel_cfg = cfg.get("release", {})
        repo = rel_cfg.get("github_repo", "")
        print(f"  github        {repo or 'NOT CONFIGURED'}")
        if repo:
            log = load_release_log(cfg)
            latest = log.get("releases", [])[-1] if log.get("releases") else None
            if latest:
                m = latest.get("meta", {})
                print(f"  latest rel    {latest.get('state')} · build {latest.get('build_id')} · "
                      f"v{m.get('aivido_version', '—')} · hash {str(m.get('content_hash_sha256', ''))[:12]}…")
    return report


# ---------------------------------------------------------------- release ----
# Global Aivido UI release pipeline. Executed ONLY on the exact approval
# phrase "OK PUBLISH UI".
#
# Public (MANDATORY — success defines PUBLIC RELEASE = LIVE):
#   PREPARE -> VALIDATE -> FREEZE -> COMMIT -> PUSH -> PUBLISH -> VERIFY -> LIVE
#
# Runtime (OPTIONAL, post-public, NEVER blocks or rolls back the public
# release): Shadow / Mac / registered installations, each reported as
# UPDATED | PENDING | OFFLINE | AUTH_REQUIRED | FAILED.
PUBLIC_RELEASE_STAGES = ["PREPARE", "VALIDATE", "FREEZE", "COMMIT", "PUSH",
                         "PUBLISH", "VERIFY", "LIVE"]

RUNTIME_STATES = ("UPDATED", "PENDING", "OFFLINE", "AUTH_REQUIRED", "FAILED")

SECRET_BLOCK_PATTERNS = [
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
]
SECRET_WARN_PATTERNS = [
    re.compile(r"(?i)(password|passwd|secret|api[_-]?key|client[_-]?secret|access[_-]?token)\s*[:=]\s*[\"'][^\"']{8,}"),
    re.compile(r"(Bearer\s+)[A-Za-z0-9._-]{20,}"),
]


def load_release_log(cfg: Dict[str, Any]) -> Dict[str, Any]:
    p = ROOT / cfg["release"]["release_root"] / "release-log.json"
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {"releases": []}
    return {"releases": []}


def save_release_log(cfg: Dict[str, Any], log: Dict[str, Any]) -> None:
    p = ROOT / cfg["release"]["release_root"] / "release-log.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(log, indent=2) + "\n", encoding="utf-8")


def next_patch_version(version: str) -> str:
    """0.1.0 -> 0.1.1 (canonical semantic-version patch bump)."""
    parts = str(version).split(".")
    while len(parts) < 3:
        parts.append("0")
    try:
        parts[2] = str(int(parts[2]) + 1)
    except ValueError:
        parts[2] = "1"
    return ".".join(parts[:3])


def secret_scan(paths: Sequence[Path]) -> Tuple[List[str], List[str]]:
    """Return (blockers, warnings) found across the given files."""
    blockers, warnings = [], []
    for p in paths:
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for idx, line in enumerate(text.splitlines(), 1):
            for pat in SECRET_BLOCK_PATTERNS:
                if pat.search(line):
                    blockers.append(f"{p}:{idx}: {pat.pattern}")
            for pat in SECRET_WARN_PATTERNS:
                if pat.search(line):
                    warnings.append(f"{p}:{idx}: {pat.pattern}")
    return blockers, warnings


def release_commit_files(cfg: Dict[str, Any], root: Optional[Path] = None) -> List[Path]:
    """Exact allowlist of files a UI release commit may touch."""
    root = root or ROOT
    ui_dir = root / cfg["canonical_ui_dir"]
    files = [ui_dir / rel for rel in inventory(ui_dir)]
    files += [ui_dir / "ui-version.json", ui_dir / "build-manifest.json",
              ui_dir / "release-manifest.json"]
    for rel in cfg["release"]["commit_paths"]:
        if rel == "ui":
            continue
        p = root / rel
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and not any(part.startswith("__pycache__") for part in f.parts):
                    files.append(f)
        elif p.is_file():
            files.append(p)
    return sorted({f for f in set(files) if f.is_file()})


def package_ui_build(build_dir: Path, package_root: Path, *, aivido_version: str,
                     ui_version: str, quiet: bool = False) -> Path:
    """Zip the frozen build (canonical UI + identity) as the portable UI release."""
    import zipfile
    package_root.mkdir(parents=True, exist_ok=True)
    out = package_root / f"aivido-ui-{aivido_version}-{ui_version}-{build_dir.name}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(build_dir.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(build_dir).as_posix())
    if not quiet:
        print(f"[ui_release] packaged {out.name} ({out.stat().st_size} bytes)")
    return out


def gh_ready(cfg: Dict[str, Any]) -> bool:
    repo = cfg.get("release", {}).get("github_repo", "")
    if not repo:
        return False
    r = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    return r.returncode == 0


def gh_release_publish(cfg: Dict[str, Any], *, tag: str, title: str, notes: str,
                       assets: Sequence[Path]) -> Tuple[bool, str]:
    """Create the GitHub release, or update it in place if it already exists
    (idempotent — allows a corrected artifact to replace the first upload)."""
    repo = cfg["release"]["github_repo"]
    notes_file = ROOT / cfg["release"]["release_root"] / f"{tag}-notes.md"
    notes_file.parent.mkdir(parents=True, exist_ok=True)
    notes_file.write_text(notes, encoding="utf-8")
    view = subprocess.run(["gh", "release", "view", tag, "--repo", repo],
                          capture_output=True, text=True, timeout=120)
    if view.returncode == 0:
        r = subprocess.run(["gh", "release", "edit", tag, "--repo", repo,
                            "--title", title, "--notes-file", str(notes_file)],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            return False, (r.stderr or r.stdout).strip()
        for a in assets:
            u = subprocess.run(["gh", "release", "upload", tag, "--repo", repo,
                                str(a), "--clobber"], capture_output=True, text=True, timeout=600)
            if u.returncode != 0:
                return False, (u.stderr or u.stdout).strip()
        return True, f"updated existing release {tag}"
    cmd = ["gh", "release", "create", tag, "--repo", repo, "--latest",
           "--title", title, "--notes-file", str(notes_file)]
    for a in assets:
        cmd.append(str(a))
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        return False, (r.stderr or r.stdout).strip()
    return True, r.stdout.strip()


def git_push_canonical(cfg: Dict[str, Any]) -> Tuple[bool, str]:
    """Fast-forward push of the release commit to the canonical public branch."""
    branch = cfg["release"]["github_branch"]
    # safety: refuse if the remote branch moved (no force, no rewrite)
    check = subprocess.run(["git", "fetch", "origin", branch], capture_output=True, text=True, timeout=120)
    if check.returncode != 0:
        return False, f"git fetch origin {branch} failed: {(check.stderr or '').strip()}"
    ok = subprocess.run(["git", "merge-base", "--is-ancestor", f"origin/{branch}", "HEAD"],
                        capture_output=True, text=True)
    if ok.returncode != 0:
        return False, f"origin/{branch} has commits not in HEAD — refusing non-fast-forward push"
    r = subprocess.run(["git", "push", "origin", f"HEAD:{branch}"],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        return False, (r.stderr or r.stdout).strip()
    return True, f"pushed HEAD -> origin/{branch}"


def deploy_remote(target_cfg: Dict[str, Any], build_id: str, *,
                  dry_run: bool = False) -> Tuple[bool, str]:
    """ssh/scp copy-only deploy to a non-local target (mac)."""
    t = target_cfg
    if not (t.get("host") and t.get("user") and t.get("ui_dir")):
        return False, (f"target not configured: need host/user/ui_dir "
                       f"(host={t.get('host') or '?'} user={t.get('user') or '?'} ui_dir={t.get('ui_dir') or '?'})")
    out_root = ROOT / cfg["build_root"]
    build_dir = out_root / build_id
    if not (build_dir / "build-manifest.json").is_file():
        return False, f"build not found: {build_dir}"
    host = t["host"]
    dest = f"{t['user']}@{host}"
    incoming = f"{t['ui_dir'].rstrip('/')}/.ui-release-incoming"
    deploy_key = Path.home() / ".ssh" / "id_ed25519_aivido_deploy"
    key_args = ["-i", str(deploy_key)] if deploy_key.is_file() else []
    remote_py = (
        "import hashlib,json,os,shutil,sys\n"
        f"src={incoming!r}; ui={t['ui_dir']!r}; bid={build_id!r}\n"
        "bk=os.path.join(ui,'..','backup','ui',bid)\n"
        "os.makedirs(bk,exist_ok=True)\n"
        "mf=json.load(open(os.path.join(src,'build-manifest.json')))\n"
        "files=list(mf['files'].keys())+['ui-version.json','build-manifest.json']\n"
        "def h(p):\n"
        "  d=hashlib.sha256();\n"
        "  with open(p,'rb') as f:\n"
        "    for c in iter(lambda:f.read(262144),b''): d.update(c)\n"
        "  return d.hexdigest()\n"
        "rec={'record_id':bid,'build_id':bid,'ui_version':mf['ui_version'],'content_hash':mf['content_hash'],'backed_up':{},'deployed':files}\n"
        "for rel in files:\n"
        "  p=os.path.join(ui,rel)\n"
        "  if os.path.isfile(p): rec['backed_up'][rel]=h(p); shutil.copy2(p,os.path.join(bk,rel))\n"
        "json.dump(rec,open(os.path.join(bk,'deploy-record.json'),'w'),indent=2)\n"
        "shutil.copy2(os.path.join(src,'build-manifest.json'),os.path.join(bk,'build-manifest.json'))\n"
        "for rel in files:\n"
        "  os.makedirs(os.path.dirname(os.path.join(ui,rel)),exist_ok=True)\n"
        "  shutil.copy2(os.path.join(src,rel),os.path.join(ui,rel))\n"
        "bad=[rel for rel in files if not os.path.isfile(os.path.join(ui,rel)) or h(os.path.join(ui,rel))!=h(os.path.join(src,rel))]\n"
        "print('DEPLOYED',bid,'files',len(files),'bad',bad)\n"
        "sys.exit(1 if bad else 0)\n"
    )
    if dry_run:
        return True, f"dry-run: scp {build_dir} -> {dest}:{incoming} then swap into {t['ui_dir']}"
    probe = subprocess.run(["ssh", *key_args, "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                            dest, "echo", "ok"], capture_output=True, text=True, timeout=30)
    if probe.returncode != 0:
        return False, f"ssh probe failed: {(probe.stderr or probe.stdout).strip()[:200]}"
    try:
        subprocess.run(["ssh", *key_args, dest, "mkdir", "-p", incoming], check=True, timeout=60)
        subprocess.run(["scp", *key_args, "-r", str(build_dir) + "/.", f"{dest}:{incoming}/"],
                       check=True, timeout=600)
        proc = subprocess.run(["ssh", *key_args, dest, "python3", "-c", remote_py],
                              capture_output=True, text=True, timeout=300)
    except Exception as exc:
        return False, f"remote deploy error: {exc}"
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout).strip()[:300]
    return True, f"deployed to {dest}:{t['ui_dir']} ({proc.stdout.strip()})"


def mac_discover(cfg: Dict[str, Any], target: str = "mac") -> Tuple[bool, Dict[str, Any]]:
    """After SSH is authorized, auto-discover user + repo ui_dir on the Mac."""
    t = cfg.get("targets", {}).get(target, {})
    if not t.get("host"):
        return False, {}
    deploy_key = Path.home() / ".ssh" / "id_ed25519_aivido_deploy"
    key_args = ["-i", str(deploy_key)] if deploy_key.is_file() else []
    # probe a couple of likely usernames via whoami
    found = {}
    for user in (t.get("user") or "", "armin", "audiovido", "shadow"):
        if not user:
            continue
        dest = f"{user}@{t['host']}"
        r = subprocess.run(["ssh", *key_args, "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                            dest, "whoami"], capture_output=True, text=True, timeout=20)
        if r.returncode == 0 and r.stdout.strip():
            found["user"] = user
            break
    if not found:
        return False, {"error": "no ssh user answered — run the one-time Mac command and retry"}
    # locate the repo ui dir
    probes = ["$HOME/Desktop/Unreal-Agent", "$HOME/Unreal-Agent", "$HOME/Documents/Unreal-Agent", "$HOME/Desktop/audiovido/unreal-agent"]
    dest = f"{found['user']}@{t['host']}"
    for probe in probes:
        r = subprocess.run(["ssh", *key_args, "-o", "BatchMode=yes", dest,
                            f"test -f {probe}/ui/ava.html && echo OK"],
                           capture_output=True, text=True, timeout=20)
        if r.returncode == 0 and "OK" in r.stdout:
            found["ui_dir"] = probe
            break
    if "ui_dir" not in found:
        found["ui_dir"] = ""
        found["error"] = f"ssh ok as {found['user']} but no Unreal-Agent ui/ found under: {', '.join(probes)}"
    return bool(found.get("ui_dir")), found


def fresh_install_verify(cfg: Dict[str, Any], build_dir: Path) -> Tuple[bool, str]:
    """Clone the public canonical branch and prove the fresh UI == approved build."""
    import tempfile
    repo = cfg["release"]["github_repo"]
    branch = cfg["release"]["github_branch"]
    manifest = json.loads((build_dir / "build-manifest.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="aivido-fresh-") as td:
        r = subprocess.run(["git", "clone", "--depth", "1", "--branch", branch,
                            f"https://github.com/{repo}.git", td],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            return False, f"clone failed: {(r.stderr or r.stdout).strip()[:200]}"
        fresh = Path(td)
        bad = []
        for rel, want in manifest.get("files", {}).items():
            p = fresh / "ui" / rel
            if not p.is_file():
                bad.append(f"{rel}:missing")
            elif sha256_file(p) != want:
                bad.append(f"{rel}:hash")
        fresh_ver = fresh / "ui" / "ui-version.json"
        if fresh_ver.is_file():
            v = json.loads(fresh_ver.read_text(encoding="utf-8"))
            if v.get("content_hash") != manifest.get("content_hash"):
                bad.append("ui-version.json:content_hash")
        else:
            bad.append("ui-version.json:missing")
        if bad:
            return False, "; ".join(bad[:8])
        return True, f"fresh clone of {repo}@{branch} matches approved build ({len(manifest['files'])} files)"


def verify_update_link(cfg: Dict[str, Any], expected_hash: str) -> Tuple[bool, str]:
    """Public raw ui-version.json on the canonical branch must carry the approved hash."""
    url = cfg["release"].get("raw_ui_version_url", "")
    if not url:
        return False, "raw_ui_version_url not configured"
    try:
        status, body, _ = _http_get(url, timeout=20)
    except Exception as exc:
        return False, f"GET {url}: {exc}"
    if status != 200:
        return False, f"HTTP {status} from {url}"
    try:
        v = json.loads(body.decode("utf-8"))
    except Exception:
        return False, f"{url} did not return JSON"
    ok = v.get("content_hash") == expected_hash
    detail = (f"{url}: build {v.get('build_id')} v{v.get('ui_version')} "
              f"hash {v.get('content_hash', '')[:12]}…")
    return ok, detail


# ---------------------------------------------------------------- runtime ----
# Optional runtime installations consume the PUBLIC release (GitHub Release /
# canonical main) via a portable updater. Public release never depends on them.

INSTALLATIONS_FILE = ROOT / "config" / "aivido_installations.json"


def load_installations() -> List[Dict[str, Any]]:
    if INSTALLATIONS_FILE.is_file():
        try:
            data = json.loads(INSTALLATIONS_FILE.read_text(encoding="utf-8"))
            return data.get("installations", []) if isinstance(data, dict) else []
        except Exception:
            return []
    return []


def save_installations(installations: List[Dict[str, Any]]) -> None:
    INSTALLATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    INSTALLATIONS_FILE.write_text(
        json.dumps({"installations": installations}, indent=2) + "\n", encoding="utf-8")


def public_latest_version(cfg: Dict[str, Any], timeout: float = 20.0) -> Tuple[bool, Dict[str, Any]]:
    """Query the PUBLIC canonical source for the latest approved release identity."""
    url = cfg.get("release", {}).get("raw_ui_version_url", "")
    if not url:
        return False, {}
    try:
        status, body, _ = _http_get(url, timeout=timeout)
    except Exception:
        return False, {}
    if status != 200:
        return False, {}
    try:
        return True, json.loads(body.decode("utf-8"))
    except Exception:
        return False, {}


def latest_release_asset_url(cfg: Dict[str, Any]) -> Tuple[bool, str]:
    """Resolve the downloadable UI package from the public GitHub latest release.
    Uses the unauthenticated public API so any machine (no gh, no token) can update."""
    repo = cfg.get("release", {}).get("github_repo", "")
    if not repo:
        return False, ""
    api_url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        status, body, _ = _http_get(api_url, timeout=20)
    except Exception:
        return False, ""
    if status != 200:
        return False, ""
    try:
        data = json.loads(body.decode("utf-8"))
    except Exception:
        return False, ""
    for asset in data.get("assets", []) or []:
        name = asset.get("name", "")
        if name.startswith("aivido-ui-") and name.endswith(".zip"):
            return True, asset.get("browser_download_url", "")
    return False, ""


def update_check(cfg: Dict[str, Any], ui_dir: Path) -> Tuple[bool, Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Compare local ui-version.json against the public canonical source.
    Returns (update_available, local, public)."""
    local = None
    p = ui_dir / "ui-version.json"
    if p.is_file():
        try:
            local = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            local = None
    ok, pub = public_latest_version(cfg)
    if not ok or not pub:
        return False, local, None
    if local is None or not local.get("content_hash"):
        return True, local, pub
    if pub.get("content_hash") == local.get("content_hash"):
        return False, local, pub
    # build_id format YYYYMMDD-HHMMSS is lexicographically comparable
    newer = str(pub.get("build_id", "")) > str(local.get("build_id", ""))
    return bool(newer), local, pub


def update_runtime_install(cfg: Dict[str, Any], ui_dir: Path, backup_root: Path, *,
                          dry_run: bool = False, quiet: bool = False) -> Tuple[bool, str]:
    """Portable updater: download the PUBLIC release package, verify SHA-256,
    backup the current release, install atomically (copy-only), verify local
    health, and roll back on any failure. Never touches config/projects/user
    data (only ui/ is ever written)."""
    ok, pub = public_latest_version(cfg)
    if not ok or not pub:
        return False, "public latest unreachable (offline or not published yet)"
    has, local, _ = update_check(cfg, ui_dir)
    if not has and local and local.get("content_hash") == pub.get("content_hash"):
        return True, f"already up to date (build {pub.get('build_id')})"
    ok_url, url = latest_release_asset_url(cfg)
    if not ok_url or not url:
        return False, "no downloadable package on the public latest release"
    if dry_run:
        return True, (f"dry-run: would download {url} → verify → backup → install into {ui_dir}")
    import io
    import zipfile
    try:
        status, body, _ = _http_get(url, timeout=120)
    except Exception as exc:
        return False, f"download failed: {exc}"
    if status != 200:
        return False, f"download HTTP {status}"
    build_dir = ui_dir.parent / f".aivido-update-{pub.get('build_id')}"
    if build_dir.exists():
        shutil.rmtree(build_dir)
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            zf.extractall(build_dir)
    except Exception as exc:
        return False, f"package corrupt: {exc}"
    manifest_path = build_dir / "build-manifest.json"
    if not manifest_path.is_file():
        return False, "package missing build-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("content_hash") != pub.get("content_hash"):
        return False, "package content_hash != public ui-version.json — refusing install"
    bad = [rel for rel, want in manifest.get("files", {}).items()
           if not (build_dir / rel).is_file() or sha256_file(build_dir / rel) != want]
    if bad:
        shutil.rmtree(build_dir, ignore_errors=True)
        return False, "package hash verification failed: " + "; ".join(bad[:5])
    # atomic install (backup + copy-only + verify) with rollback on failure
    try:
        deploy_build(build_dir, ui_dir, backup_root, quiet=True)
    except Exception as exc:
        shutil.rmtree(build_dir, ignore_errors=True)
        return False, f"install failed ({exc}); no changes were applied"
    verify = verify_build_local(build_dir, quiet=True)
    local_ok = all(c["ok"] for c in verify)
    served = None
    base = cfg.get("targets", {}).get("shadow", {}).get("base_url")
    if local_ok and base:
        try:
            status, body, _ = _http_get(f"{base}/static/ui-version.json", timeout=6)
            if status == 200:
                served = json.loads(body.decode("utf-8")).get("content_hash")
        except Exception:
            served = None
    if local_ok and (served is None or served == pub.get("content_hash")):
        shutil.rmtree(build_dir, ignore_errors=True)
        return True, (f"updated to build {pub.get('build_id')} · hash verified · "
                      + ("local server confirms" if served else "server not probed (no live endpoint)"))
    # rollback to previous known-good
    try:
        rollback(ui_dir, backup_root, pub.get("build_id"), quiet=True)
        shutil.rmtree(build_dir, ignore_errors=True)
        return False, "post-install verification failed — rolled back to previous release"
    except Exception as exc:
        shutil.rmtree(build_dir, ignore_errors=True)
        return False, f"post-install verification failed AND rollback failed: {exc}"


def verify_release_assets(cfg: Dict[str, Any], build_id: str, expected_hash: str) -> Tuple[bool, str]:
    """Download the published UI package from the GitHub latest release and
    prove its contents hash-match the approved build (downloadable artifact
    verification). Requires gh (release may be private-in-progress)."""
    repo = cfg.get("release", {}).get("github_repo", "")
    if not repo:
        return False, "github_repo not configured"
    tag = f"v{cfg.get('aivido_version', '')}"
    r = subprocess.run(["gh", "release", "view", tag, "--repo", repo, "--json", "assets",
                        "--jq", ".assets[].name"], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        return False, f"gh release view failed: {(r.stderr or '').strip()[:160]}"
    names = [n for n in r.stdout.splitlines() if n.startswith("aivido-ui-") and n.endswith(".zip")]
    if not names:
        return False, "no aivido-ui-*.zip asset on the release"
    import tempfile, zipfile
    with tempfile.TemporaryDirectory(prefix="aivido-asset-") as td:
        dl = subprocess.run(["gh", "release", "download", tag, "--repo", repo,
                             "--pattern", names[0], "--dir", td, "--clobber"],
                            capture_output=True, text=True, timeout=300)
        if dl.returncode != 0:
            return False, f"gh release download failed: {(dl.stderr or '').strip()[:160]}"
        zpath = Path(td) / names[0]
        with zipfile.ZipFile(zpath) as zf:
            zf.extractall(td)
        out_root = ROOT / cfg["build_root"]
        build_dir = out_root / build_id
        manifest = json.loads((build_dir / "build-manifest.json").read_text(encoding="utf-8"))
        bad = []
        for rel, want in manifest.get("files", {}).items():
            p = Path(td) / rel
            if not p.is_file():
                bad.append(f"{rel}:missing")
            elif sha256_file(p) != want:
                bad.append(f"{rel}:hash")
        ver = Path(td) / "ui-version.json"
        if ver.is_file():
            v = json.loads(ver.read_text(encoding="utf-8"))
            if v.get("content_hash") != expected_hash:
                bad.append("ui-version.json:content_hash")
        else:
            bad.append("ui-version.json:missing")
        if bad:
            return False, "asset hash mismatch: " + "; ".join(bad[:6])
        return True, f"release asset {names[0]} matches approved build"


def runtime_pass(cfg: Dict[str, Any], build_id: str, *, dry_run: bool = False) -> List[Dict[str, Any]]:
    """Post-public optional runtime updates. Never raises; never blocks the
    public release. Each target reports UPDATED/PENDING/OFFLINE/AUTH_REQUIRED/FAILED."""
    build_dir = ROOT / cfg["build_root"] / build_id
    backup_root = ROOT / cfg["backup_root"]
    results: List[Dict[str, Any]] = []
    seen = set()
    for name, t in list(cfg.get("targets", {}).items()):
        seen.add(name)
        state, detail = "PENDING", ""
        if t.get("type") == "local":
            try:
                deploy_build(build_dir, ROOT / t["ui_dir"], backup_root, quiet=True, dry_run=dry_run)
                state = "UPDATED" if not dry_run else "PENDING"
                detail = f"deployed {build_id}"
            except Exception as exc:
                state, detail = "FAILED", str(exc)
        elif t.get("type") == "ssh":
            if not (t.get("host") and t.get("user") and t.get("ui_dir")):
                state, detail = "AUTH_REQUIRED", "host/user/ui_dir not configured (one-time Mac command)"
            else:
                ok, detail = deploy_remote(t, build_id, dry_run=dry_run)
                if ok:
                    state = "UPDATED" if not dry_run else "PENDING"
                else:
                    state = "FAILED" if "probe failed" in detail or "remote deploy" in detail else "OFFLINE"
                    state = "AUTH_REQUIRED" if "not configured" in detail else state
        results.append({"name": name, "type": t.get("type", "?"), "state": state, "detail": detail})
    for inst in load_installations():
        name = inst.get("name", "?")
        if name in seen:
            continue
        seen.add(name)
        state, detail = "PENDING", ""
        if inst.get("type") == "local":
            try:
                deploy_build(build_dir, Path(inst["ui_dir"]), backup_root, quiet=True, dry_run=dry_run)
                state = "UPDATED" if not dry_run else "PENDING"
                detail = f"deployed {build_id}"
            except Exception as exc:
                state, detail = "FAILED", str(exc)
        elif inst.get("type") == "ssh":
            if not (inst.get("host") and inst.get("user") and inst.get("ui_dir")):
                state, detail = "AUTH_REQUIRED", "host/user/ui_dir not configured"
            else:
                ok, detail = deploy_remote(inst, build_id, dry_run=dry_run)
                state = "UPDATED" if ok else ("AUTH_REQUIRED" if "not configured" in detail else "FAILED")
        results.append({"name": name, "type": inst.get("type", "?"), "state": state, "detail": detail})
    return results


def _write_release_identity(build_dir: Path, cfg: Dict[str, Any], aivido_version: str) -> Dict[str, Any]:
    """FREEZE: write the full release identity into the frozen build.
    ui-version.json is rewritten too so the SAME identity is visible on every
    target (ui-version.json / release-manifest.json / GitHub tag agree)."""
    manifest = json.loads((build_dir / "build-manifest.json").read_text(encoding="utf-8"))
    identity = {
        "aivido_version": aivido_version,
        "ui_version": manifest["ui_version"],
        "build_id": manifest["build_id"],
        "git_sha": manifest["git_sha"],
        "build_timestamp": manifest["timestamp"],
        "content_hash_sha256": manifest["content_hash"],
    }
    (build_dir / "release-manifest.json").write_text(
        json.dumps(identity, indent=2) + "\n", encoding="utf-8")
    vpath = build_dir / "ui-version.json"
    if vpath.is_file():
        try:
            version = json.loads(vpath.read_text(encoding="utf-8"))
        except Exception:
            version = {}
        version["aivido_version"] = aivido_version
        vpath.write_text(json.dumps(version, indent=2) + "\n", encoding="utf-8")
    return identity


def run_release(cfg: Dict[str, Any], *, build_id: str, resume_from: str = "PREPARE",
                patch_version: bool = False, dry_run: bool = False) -> int:
    """Public-first atomic release. The MANDATORY public chain (GitHub) defines
    success; runtime installations (Shadow/Mac/registry) are updated AFTER and
    NEVER block or roll back the public release."""
    log = load_release_log(cfg)
    rel = {"build_id": build_id, "state": "PREPARE", "stages": {}, "meta": {}, "runtime": []}
    log["releases"].append(rel)
    save_release_log(cfg, log)

    out_root = ROOT / cfg["build_root"]
    build_dir = out_root / build_id
    if not (build_dir / "build-manifest.json").is_file():
        print(f"[ui_release] RELEASE FAIL: build not found: {build_dir}")
        return 1
    if dry_run:
        print(f"[ui_release] RELEASE DRY-RUN for build {build_id}")

    def mark(stage: str, ok: bool, detail: str = "") -> None:
        rel["stages"][stage] = {"ok": ok, "ts": utc_now(), "detail": detail}
        rel["state"] = "FAIL" if not ok else stage
        save_release_log(cfg, log)
        print(f"  [{'PASS' if ok else 'FAIL'}] {stage}: {detail}")

    started = False
    for stage in PUBLIC_RELEASE_STAGES:
        if stage == resume_from:
            started = True
        if not started:
            continue
        try:
            if stage == "PREPARE":
                if patch_version:
                    cfg["aivido_version"] = next_patch_version(cfg.get("aivido_version", "0.1.0"))
                    cfg_path = ROOT / "config" / "ui_release.json"
                    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
                identity = _write_release_identity(build_dir, cfg, cfg.get("aivido_version", "0.1.0"))
                rel["meta"] = identity
                ui_dir = ROOT / cfg["canonical_ui_dir"]
                # freeze source: canonical ui/ == the frozen build, byte for byte
                # (cache-bust refs, ui-version.json, manifests). The release
                # commit therefore carries exactly the approved artifact.
                if not dry_run:
                    for src in sorted(build_dir.rglob("*")):
                        if src.is_file():
                            _copy_file(src, ui_dir / src.relative_to(build_dir))
                mark("PREPARE", True, f"frozen {build_id} · aivido {identity['aivido_version']} · ui {identity['ui_version']}")
            elif stage == "VALIDATE":
                checks = verify_build_local(build_dir, quiet=True)
                ok = all(c["ok"] for c in checks)
                r = subprocess.run([sys.executable, "-m", "pytest", "tests/test_ui_release.py", "-q"],
                                   cwd=str(ROOT), capture_output=True, text=True, timeout=600)
                tests_ok = r.returncode == 0
                mark("VALIDATE", ok and tests_ok,
                     f"build {len(checks)}/{len(checks)} checks · pytest {'PASS' if tests_ok else 'FAIL'}")
            elif stage == "FREEZE":
                blockers, warns = secret_scan(release_commit_files(cfg))
                for w in warns[:10]:
                    print(f"    scan-warn: {w}")
                mark("FREEZE", not blockers,
                     f"secret scan: {len(blockers)} blocker(s)" + (f" — {blockers[0]}" if blockers else " · clean"))
            elif stage == "COMMIT":
                paths = [str(p.relative_to(ROOT)) for p in release_commit_files(cfg)]
                if dry_run:
                    mark("COMMIT", True, f"dry-run: would stage {len(paths)} allowlisted files")
                    continue
                st = subprocess.run(["git", "add", "--", *paths], capture_output=True, text=True)
                if st.returncode != 0:
                    mark("COMMIT", False, f"git add: {(st.stderr or '').strip()[:200]}")
                    continue
                staged = subprocess.run(["git", "diff", "--cached", "--name-only"],
                                        capture_output=True, text=True)
                n = len(staged.stdout.splitlines()) if staged.returncode == 0 else 0
                msg = f"Aivido UI Release {cfg.get('ui_version', '')} ({build_id})"
                c = subprocess.run(["git", "commit", "-m", msg], capture_output=True, text=True)
                if c.returncode != 0:
                    mark("COMMIT", False, (c.stderr or c.stdout or "").strip()[:200])
                    continue
                sha = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"],
                                     capture_output=True, text=True).stdout.strip()
                mark("COMMIT", True, f"{n} files · {sha} · '{msg}'")
            elif stage == "PUSH":
                if dry_run:
                    mark("PUSH", True, "dry-run: would push to origin/" + cfg["release"]["github_branch"])
                    continue
                ok, detail = git_push_canonical(cfg)
                mark("PUSH", ok, detail)
            elif stage == "PUBLISH":
                if dry_run:
                    mark("PUBLISH", True, "dry-run: would gh release create v" + cfg.get("aivido_version", ""))
                    continue
                if not gh_ready(cfg):
                    mark("PUBLISH", False, "gh not authenticated — run 'gh auth login' once")
                    continue
                tag = f"v{cfg.get('aivido_version', '')}"
                notes = (f"# Aivido UI Release {cfg.get('ui_version', '')} ({build_id})\n\n"
                         f"- AIVIDO_VERSION: {cfg.get('aivido_version')}\n"
                         f"- UI_VERSION: {cfg.get('ui_version')}\n"
                         f"- BUILD_ID: {build_id}\n"
                         f"- GIT_SHA: {rel['meta'].get('git_sha')}\n"
                         f"- CONTENT_HASH_SHA256: {rel['meta'].get('content_hash_sha256')}\n\n"
                         f"Artifacts: canonical UI zip + product package. Install: replace the `ui/` "
                         f"directory of your Aivido install with this archive's contents, or run "
                         f"`python scripts/aivido_update.py update`.\n")
                pkg = package_ui_build(build_dir, ROOT / cfg["release"]["package_root"],
                                       aivido_version=cfg.get("aivido_version", "0.1.0"),
                                       ui_version=cfg.get("ui_version", ""))
                rel["meta"]["package"] = str(pkg.relative_to(ROOT))
                save_release_log(cfg, log)
                ok, detail = gh_release_publish(cfg, tag=tag, title=f"Aivido v{cfg.get('aivido_version')}",
                                                notes=notes, assets=[pkg])
                mark("PUBLISH", ok, detail or tag)
            elif stage == "VERIFY":
                checks = []
                if dry_run:
                    mark("VERIFY", True, "dry-run: public checks run after real publish")
                    continue
                if cfg["release"].get("raw_ui_version_url"):
                    ok, detail = verify_update_link(cfg, rel["meta"].get("content_hash_sha256", ""))
                    checks.append({"name": "public raw ui-version.json", "ok": ok, "detail": detail})
                if not any("HTTP" in c.get("detail", "") and "ui-version" in c.get("name", "") for c in checks):
                    try:
                        ok, detail = fresh_install_verify(cfg, build_dir)
                        checks.append({"name": "fresh install (clone)", "ok": ok, "detail": detail})
                    except Exception as exc:
                        checks.append({"name": "fresh install (clone)", "ok": False, "detail": str(exc)})
                ok, detail = verify_release_assets(cfg, build_id, rel["meta"].get("content_hash_sha256", ""))
                checks.append({"name": "downloadable release artifact", "ok": ok, "detail": detail})
                if not all(c["ok"] for c in checks):
                    # raw GitHub + fresh clone can lag the push by seconds — retry once
                    print("    public checks not green yet — waiting 6s and retrying…")
                    time.sleep(6)
                    checks = []
                    ok, detail = verify_update_link(cfg, rel["meta"].get("content_hash_sha256", ""))
                    checks.append({"name": "public raw ui-version.json", "ok": ok, "detail": detail})
                    try:
                        ok2, detail2 = fresh_install_verify(cfg, build_dir)
                        checks.append({"name": "fresh install (clone)", "ok": ok2, "detail": detail2})
                    except Exception as exc:
                        checks.append({"name": "fresh install (clone)", "ok": False, "detail": str(exc)})
                    ok3, detail3 = verify_release_assets(cfg, build_id, rel["meta"].get("content_hash_sha256", ""))
                    checks.append({"name": "downloadable release artifact", "ok": ok3, "detail": detail3})
                mark("VERIFY", all(c["ok"] for c in checks),
                     f"{sum(1 for c in checks if c['ok'])}/{len(checks)} checks green")
            elif stage == "LIVE":
                mark("LIVE", True, f"PUBLIC RELEASE LIVE — Aivido v{cfg.get('aivido_version')} · UI {cfg.get('ui_version')} · {build_id} "
                     + ("(DRY-RUN, not published)" if dry_run else "on GitHub main + latest release"))
                rel["state"] = "DRY-RUN" if dry_run else "LIVE"
                save_release_log(cfg, log)
        except Exception as exc:  # noqa: BLE001
            mark(stage, False, str(exc))
        if not rel["stages"][stage]["ok"]:
            rel["state"] = "FAIL"
            save_release_log(cfg, log)
            print(f"\n[ui_release] RELEASE FAIL at {stage} — public release NOT live. "
                  f"No runtime deployment was attempted.")
            return 1

    # ---- post-public: OPTIONAL runtime updates (never block, never roll back) ----
    print("\n[ui_release] public release LIVE — updating optional runtime installations…")
    try:
        rel["runtime"] = runtime_pass(cfg, build_id, dry_run=dry_run)
    except Exception as exc:  # noqa: BLE001
        rel["runtime"] = [{"name": "runtime", "type": "?", "state": "FAILED", "detail": str(exc)}]
    for r in rel["runtime"]:
        print(f"  [RUNTIME {r['state']}] {r['name']} ({r['type']}): {r['detail']}")
    save_release_log(cfg, log)

    print(f"\n[ui_release] RELEASE {'DRY-RUN ' if dry_run else ''}COMPLETE — PUBLIC RELEASE {'DRY-RUN' if dry_run else 'LIVE'}")
    _print_release_report(cfg, rel)
    return 0


def _print_release_report(cfg: Dict[str, Any], rel: Dict[str, Any]) -> None:
    meta = rel.get("meta", {})
    stages = rel.get("stages", {})
    public_ok = rel.get("state") in ("LIVE", "DRY-RUN")
    print("\n================ AIVIDO RELEASE REPORT ================")
    print(f"PUBLIC RELEASE: {'PASS' if public_ok else 'FAIL'}")
    print(f"AIVIDO VERSION: {meta.get('aivido_version', '—')}")
    print(f"UI VERSION:     {meta.get('ui_version', '—')}")
    print(f"BUILD ID:       {meta.get('build_id', '—')}")
    print(f"GIT SHA:        {meta.get('git_sha', '—')}")
    print(f"CONTENT HASH:   {meta.get('content_hash_sha256', '—')}")
    g = lambda s: "PASS" if stages.get(s, {}).get("ok") else "FAIL"  # noqa: E731
    print(f"GITHUB MAIN:            {g('PUSH')}")
    print(f"GITHUB LATEST RELEASE:  {g('PUBLISH')}")
    print(f"FRESH CLONE:            {g('VERIFY')}")
    print(f"DOWNLOAD PACKAGE:       {g('VERIFY')}")
    for r in rel.get("runtime", []):
        print(f"{r.get('name', '?').upper():<7} {r.get('type', '?'):<5} {r.get('state'):<14} {r.get('detail', '')}")
    repo = cfg.get("release", {}).get("github_repo", "")
    print(f"PUBLIC LINK:        https://github.com/{repo}")
    print(f"LATEST RELEASE LINK: https://github.com/{repo}/releases/latest")
    print(f"ROLLBACK POINT:     backup record {meta.get('build_id', '—')} (rollback --to {meta.get('build_id', '—')})")
    print(f"BLOCKERS:           {rel.get('blockers') or 'none'}")
    print("=======================================================")


# ---------------------------------------------------------------- CLI ----
def _resolve_ui_dir(cfg: Dict[str, Any], args: argparse.Namespace) -> Path:
    return Path(args.ui_dir) if getattr(args, "ui_dir", None) else ROOT / cfg["canonical_ui_dir"]


def cmd_manifest(args: argparse.Namespace, cfg: Dict[str, Any]) -> int:
    ui_dir = _resolve_ui_dir(cfg, args)
    inv = inventory(ui_dir)
    print(f"[ui_release] canonical UI inventory: {len(inv)} files in {ui_dir}")
    for rel, sha in inv.items():
        print(f"  {sha}  {rel}")
    out = Path(args.out) if getattr(args, "out", None) else ROOT / "dist"
    out.mkdir(parents=True, exist_ok=True)
    (out / "ui-manifest.json").write_text(json.dumps(inv, indent=2) + "\n", encoding="utf-8")
    print(f"  saved -> {out / 'ui-manifest.json'}")
    return 0


def cmd_build(args: argparse.Namespace, cfg: Dict[str, Any]) -> int:
    ui_dir = _resolve_ui_dir(cfg, args)
    out_root = Path(args.out) if getattr(args, "out", None) else ROOT / cfg["build_root"]
    result = build(
        ui_dir, out_root,
        product=cfg["product"], aivido_version=cfg.get("aivido_version", "0.1.0"),
        ui_version=args.ui_version or cfg["ui_version"],
        build_id=args.build_id,
    )
    # auto-stage the freshly built iteration for review
    stage(out_root, ROOT / cfg["staging"]["dir"], result["build_id"])
    return 0


def cmd_stage(args: argparse.Namespace, cfg: Dict[str, Any]) -> int:
    out_root = Path(args.out) if getattr(args, "out", None) else ROOT / cfg["build_root"]
    staging_root = ROOT / cfg["staging"]["dir"]
    build_id = args.build_id or current_staged_build(staging_root) or ""
    if not build_id:
        print("no build id given and nothing staged yet — run 'build' first")
        return 1
    stage(out_root, staging_root, build_id)
    return 0


def cmd_serve(args: argparse.Namespace, cfg: Dict[str, Any]) -> int:
    import uvicorn
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import ui_staging_server

    out_root = Path(args.out) if getattr(args, "out", None) else ROOT / cfg["build_root"]
    staging_root = ROOT / cfg["staging"]["dir"]
    build_id = args.build_id or current_staged_build(staging_root) or ""
    if not build_id:
        print("no build staged — run 'build' or 'stage' first")
        return 1
    backend = args.backend or cfg["staging"]["backend"]
    if args.build_id:
        build_dir = out_root / build_id
        if not (build_dir / "build-manifest.json").is_file():
            print(f"staged build missing: {build_dir}")
            return 1
        app = ui_staging_server.create_app(build_dir, backend)
        label = f"build {build_id} (pinned)"
    else:
        # dynamic: serves whatever build is currently staged — rebuild,
        # restage, then just refresh the browser (no server restart).
        app = ui_staging_server.create_app(None, backend, dynamic=True)
        label = f"build {build_id} (dynamic)"
    port = int(args.port or cfg["staging"]["port"])
    print(f"[ui_release] staging server: http://127.0.0.1:{port}/  "
          f"({label} · /api -> {backend})")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    return 0


def _target_ui_dir(cfg: Dict[str, Any], target: str, override: Optional[str]) -> Tuple[Path, Dict[str, Any]]:
    t = cfg.get("targets", {}).get(target)
    if t is None:
        raise SystemExit(f"unknown target '{target}' (known: {', '.join(cfg.get('targets', {}))})")
    if override:
        ui_dir = Path(override)
    elif t.get("type") == "local":
        ui_dir = ROOT / t["ui_dir"]
    else:
        raise SystemExit(
            f"target '{target}' is type '{t.get('type')}' — the local deploy path only handles local "
            f"targets; use 'deploy-remote' for ssh/scp targets")
    return ui_dir, t


def cmd_deploy(args: argparse.Namespace, cfg: Dict[str, Any]) -> int:
    out_root = Path(args.out) if getattr(args, "out", None) else ROOT / cfg["build_root"]
    backup_root = ROOT / cfg["backup_root"]
    build_id = args.build_id or current_staged_build(ROOT / cfg["staging"]["dir"]) or ""
    if not build_id:
        print("no build id given and nothing staged — run 'build' first")
        return 1
    build_dir = out_root / build_id
    if not (build_dir / "build-manifest.json").is_file():
        print(f"build not found: {build_dir}")
        return 1
    ui_dir, _ = _target_ui_dir(cfg, args.target, args.ui_dir)
    result = deploy_build(build_dir, ui_dir, backup_root, dry_run=args.dry_run)
    if args.dry_run:
        print(f"[ui_release] DRY-RUN: would deploy build {build_id} -> {ui_dir} "
              f"(backup under {backup_root})")
        for rel in sorted(result["backed_up"]):
            print(f"  backup {rel}")
        return 0
    print(f"[ui_release] deployed build {build_id} -> {ui_dir}")
    if args.verify:
        verify_build_local(build_dir)
        verify_target([cfg["targets"][args.target].get("base_url", DEFAULT_BACKEND)], build_dir)
    return 0


def cmd_deploy_remote(args: argparse.Namespace, cfg: Dict[str, Any]) -> int:
    """Deploy to a non-local target (mac) over ssh/scp, cross-platform."""
    build_id = args.build_id or current_staged_build(ROOT / cfg["staging"]["dir"]) or ""
    if not build_id:
        raise SystemExit("no build id given and nothing staged")
    t = cfg.get("targets", {}).get(args.target)
    if t is None:
        raise SystemExit(f"unknown target '{args.target}'")
    ok, detail = deploy_remote(t, build_id, dry_run=args.dry_run)
    print(detail)
    if not ok:
        raise SystemExit(f"remote deploy failed: {detail}")
    return 0


def cmd_verify(args: argparse.Namespace, cfg: Dict[str, Any]) -> int:
    checks: List[Dict[str, Any]] = []
    out_root = Path(args.out) if getattr(args, "out", None) else ROOT / cfg["build_root"]
    build_dir = None
    if args.build:
        build_dir = out_root / args.build
        if not (build_dir / "build-manifest.json").is_file():
            print(f"build not found: {build_dir}")
            return 1
        checks += verify_build_local(build_dir)
    urls = [u for u in (args.url or []) if u]
    if urls:
        checks += verify_target(urls, build_dir, timeout=args.timeout)
    elif not build_dir:
        print("nothing to verify — pass --build <id> and/or --url <base>")
        return 1
    failed = [c for c in checks if not c["ok"]]
    print(f"\n[ui_release] VERIFY {'PASS' if not failed else 'FAIL'} — {len(checks) - len(failed)}/{len(checks)} checks green")
    return 0 if not failed else 2


def cmd_rollback(args: argparse.Namespace, cfg: Dict[str, Any]) -> int:
    backup_root = ROOT / cfg["backup_root"]
    ui_dir, _ = _target_ui_dir(cfg, args.target, args.ui_dir)
    result = rollback(ui_dir, backup_root, args.to, dry_run=args.dry_run)
    if args.dry_run:
        print("[ui_release] ROLLBACK DRY-RUN — no changes written")
        return 0
    return 0


def cmd_release(args: argparse.Namespace, cfg: Dict[str, Any]) -> int:
    build_id = args.build_id or current_staged_build(ROOT / cfg["staging"]["dir"]) or ""
    if not build_id:
        print("no build id given and nothing staged — run 'build' first")
        return 1
    if args.resume not in PUBLIC_RELEASE_STAGES:
        print(f"unknown resume stage '{args.resume}' (one of: {', '.join(PUBLIC_RELEASE_STAGES)})")
        return 1
    if not cfg.get("release", {}).get("github_repo"):
        print("release not configured: set release.github_repo in config/ui_release.json")
        return 1
    return run_release(cfg, build_id=build_id, resume_from=args.resume,
                       patch_version=args.patch_version, dry_run=args.dry_run)


def cmd_release_status(args: argparse.Namespace, cfg: Dict[str, Any]) -> int:
    log = load_release_log(cfg)
    if not log.get("releases"):
        print("[ui_release] no releases recorded yet")
        return 0
    for rel in reversed(log["releases"]):
        meta = rel.get("meta", {})
        print(f"  {rel.get('state', '?'):<8} build {rel.get('build_id')} · "
              f"aivido {meta.get('aivido_version', '—')} · ui {meta.get('ui_version', '—')} · "
              f"hash {str(meta.get('content_hash_sha256', ''))[:12]}…")
        for st, info in rel.get("stages", {}).items():
            print(f"      {'PASS' if info.get('ok') else 'FAIL'} {st}: {info.get('detail', '')}")
        for r in rel.get("runtime", []):
            print(f"      RUNTIME {r.get('state'):<14} {r.get('name')}: {r.get('detail', '')}")
    return 0


def cmd_mac_discover(args: argparse.Namespace, cfg: Dict[str, Any]) -> int:
    ok, info = mac_discover(cfg, args.target)
    print(json.dumps(info, indent=2))
    if not ok:
        print(f"[ui_release] mac-discover: {info.get('error', 'no result')}")
        return 1
    # persist into config for the release pipeline
    t = cfg["targets"][args.target]
    t["user"] = info["user"]
    t["ui_dir"] = info["ui_dir"]
    cfg_path = ROOT / "config" / "ui_release.json"
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    print(f"[ui_release] mac target configured: {info['user']}@{t['host']}:{info['ui_dir']}")
    return 0


def cmd_status(args: argparse.Namespace, cfg: Dict[str, Any]) -> int:
    status_report(cfg)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="ui_release.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=None, help="config file (default config/ui_release.json)")
    ap.add_argument("--ui-dir", default=None, help="canonical UI source dir override (default from config)")
    ap.add_argument("--out", default=None, help="build output root (default dist/ui-builds)")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("manifest", help="inventory canonical ui/ files with sha256")
    p.set_defaults(func=cmd_manifest)

    p = sub.add_parser("build", help="deterministic build -> dist/ui-builds/<build_id>/")
    p.add_argument("--ui-version", default=None, help="ui version (default from config)")
    p.add_argument("--build-id", default=None, help="explicit build id (default UTC timestamp)")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("stage", help="point staging at a build")
    p.add_argument("--build-id", default=None, help="build id to stage (default: current staged)")
    p.set_defaults(func=cmd_stage)

    p = sub.add_parser("serve", help="run the staging server (route parity + /api proxy)")
    p.add_argument("--build-id", default=None, help="build to serve (default: staged)")
    p.add_argument("--port", default=None, help=f"port (default {DEFAULT_STAGING_PORT})")
    p.add_argument("--backend", default=None, help=f"backend to proxy /api (default {DEFAULT_BACKEND})")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("deploy", help="promote a build to a local target (copy-only + backup)")
    p.add_argument("--build-id", default=None, help="build to deploy (default: staged)")
    p.add_argument("--target", default="shadow", help="target name from config (default shadow)")
    p.add_argument("--ui-dir", default=None, help="override target ui dir (safe scratch testing)")
    p.add_argument("--dry-run", action="store_true", help="compute actions, write nothing")
    p.add_argument("--verify", action="store_true", help="verify build + target after deploy")
    p.set_defaults(func=cmd_deploy)

    p = sub.add_parser("deploy-remote", help="deploy a build to an ssh/scp target (mac)")
    p.add_argument("--build-id", default=None, help="build to deploy (default: staged)")
    p.add_argument("--target", default="mac", help="target name from config (default mac)")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_deploy_remote)

    p = sub.add_parser("verify", help="hash-parity verification of build and/or live targets")
    p.add_argument("--build", default=None, help="local build id to verify offline")
    p.add_argument("--url", action="append", default=[], help="live base URL (repeatable for parity)")
    p.add_argument("--timeout", type=float, default=10.0)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("rollback", help="restore a target from a deploy backup")
    p.add_argument("--to", default=None, help="deploy record id to restore (default latest)")
    p.add_argument("--target", default="shadow", help="target name from config")
    p.add_argument("--ui-dir", default=None, help="override target ui dir (safe scratch testing)")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_rollback)

    p = sub.add_parser("release", help="GLOBAL atomic release (ONLY after 'OK PUBLISH UI')")
    p.add_argument("--build-id", default=None, help="approved frozen build (default: staged)")
    p.add_argument("--resume", default="PREPARE", help="start from stage (default PREPARE)")
    p.add_argument("--patch-version", action="store_true", help="bump aivido_version patch (0.1.0 -> 0.1.1)")
    p.add_argument("--dry-run", action="store_true", help="simulate every stage, write/push nothing")
    p.set_defaults(func=cmd_release)

    p = sub.add_parser("release-status", help="release log + lifecycle state")
    p.set_defaults(func=cmd_release_status)

    p = sub.add_parser("mac-discover", help="auto-discover Mac ssh user + repo ui_dir")
    p.add_argument("--target", default="mac", help="target name from config")
    p.set_defaults(func=cmd_mac_discover)

    p = sub.add_parser("status", help="current build / staging / backup / target state")
    p.set_defaults(func=cmd_status)

    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    try:
        return int(args.func(args, cfg) or 0)
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
    raise SystemExit(main())