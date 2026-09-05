"""Hermetic tests for the Aivido canonical UI release pipeline.

Covers: canonical inventory, deterministic build, ui-version.json contract,
cache-busting, copy-only deploy with backup, exact rollback, offline build
verification, and live target verification (route parity + asset hash
parity) against a real staging server on a scratch port. No live backend,
no Unreal bridge, no network beyond loopback.
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ui_release as ur  # noqa: E402
from ui_staging_server import create_app  # noqa: E402

CANONICAL_FILES = {
    "ava.html": "<!doctype html><html><head><link rel=\"stylesheet\" href=\"/static/ava.css?v=7\">"
                "<script src=\"/static/ava.js?v=7\"></script><script src=\"/static/ava_widget.js?v=7\"></script>"
                "</head><body>ava</body></html>",
    "ava.css": "body{color:cyan}",
    "ava.js": "console.log('ava')",
    "ava_widget.js": "console.log('widget')",
    "aivido.html": "<!doctype html><html><head><link rel=\"stylesheet\" href=\"/static/aivido.css?v=3\">"
                   "<script src=\"/static/aivido.js?v=3\"></script></head><body>booth</body></html>",
    "aivido.css": "body{color:gold}",
    "aivido.js": "console.log('booth')",
    "index.html": "<!doctype html><html><head><link rel=\"stylesheet\" href=\"/static/styles.css?v=2\">"
                  "<script src=\"/static/app.js?v=2\"></script></head><body>dev</body></html>",
    "styles.css": "body{color:white}",
    "app.js": "console.log('dev')",
    "product.html": "<!doctype html><html><head><link rel=\"stylesheet\" href=\"/static/product.css?v=1\">"
                    "<script src=\"/static/product.js?v=1\"></script></head><body>product</body></html>",
    "product.css": "body{color:black}",
    "product.js": "console.log('product')",
    "devboard.html": "<html><body>devboard</body></html>",
    "widget_harness.html": "<html><body>harness</body></html>",
}

LEGACY_JUNK = {
    "ui.zip": b"PK\x03\x04 legacy zip bytes",
    "index.html.broken-encoding": b"\xff\xfe broken",
    "backup-20260820-081408/app.js": b"old backup",
}


def make_ui_dir(root: Path) -> Path:
    ui_dir = root / "ui"
    for rel, text in CANONICAL_FILES.items():
        p = ui_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    for rel, data in LEGACY_JUNK.items():
        p = ui_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return ui_dir


@pytest.fixture()
def ui_dir(tmp_path: Path) -> Path:
    return make_ui_dir(tmp_path)


@pytest.fixture()
def out_root(tmp_path: Path) -> Path:
    return tmp_path / "builds"


@pytest.fixture()
def backup_root(tmp_path: Path) -> Path:
    return tmp_path / "backup"


# ------------------------------------------------------------ inventory ---
def test_inventory_excludes_legacy_junk(ui_dir: Path) -> None:
    inv = ur.inventory(ui_dir)
    assert set(inv) == set(CANONICAL_FILES)
    assert "ui.zip" not in inv
    assert "index.html.broken-encoding" not in inv
    assert "backup-20260820-081408/app.js" not in inv


# ---------------------------------------------------------------- build ---
def test_build_deterministic(ui_dir: Path, out_root: Path) -> None:
    a = ur.build(ui_dir, out_root, build_id="t1", git_sha="abc123", git_dirty=False,
                 timestamp="2026-01-01T00:00:00Z")
    b = ur.build(ui_dir, out_root, build_id="t2", git_sha="abc123", git_dirty=False,
                 timestamp="2026-01-01T00:00:00Z")
    assert a["content_hash"] == b["content_hash"]
    for rel in CANONICAL_FILES:
        assert (out_root / "t1" / rel).read_bytes() == (out_root / "t2" / rel).read_bytes()
    # ui-version.json differs only in build_id
    v1 = json.loads((out_root / "t1" / "ui-version.json").read_text(encoding="utf-8"))
    v2 = json.loads((out_root / "t2" / "ui-version.json").read_text(encoding="utf-8"))
    v1.pop("build_id"), v2.pop("build_id")
    assert v1 == v2


def test_version_json_contract(ui_dir: Path, out_root: Path) -> None:
    ur.build(ui_dir, out_root, build_id="t1", git_sha="deadbeef", git_dirty=False,
             timestamp="2026-01-01T00:00:00Z")
    v = json.loads((out_root / "t1" / "ui-version.json").read_text(encoding="utf-8"))
    # the six mission-required fields are all present
    assert all(f in v for f in ur.VERSION_FIELDS)
    # plus the release identity channel (aivido_version) — no extras
    assert set(v.keys()) == set(ur.VERSION_FIELDS) | {"aivido_version"}
    assert v["product"] == "Aivido"
    assert v["aivido_version"] == "0.1.0"
    assert v["ui_version"] == "1.0.0"
    assert v["build_id"] == "t1"
    assert v["git_sha"] == "deadbeef"
    assert v["content_hash"]


def test_inventory_excludes_release_outputs(ui_dir: Path) -> None:
    # deployed builds put ui-version.json + build-manifest.json into ui/;
    # the canonical inventory must never re-absorb them
    (ui_dir / "ui-version.json").write_text(json.dumps({"x": 1}), encoding="utf-8")
    (ui_dir / "build-manifest.json").write_text(json.dumps({"x": 1}), encoding="utf-8")
    inv = ur.inventory(ui_dir)
    assert "ui-version.json" not in inv
    assert "build-manifest.json" not in inv


def test_next_patch_version() -> None:
    assert ur.next_patch_version("0.1.0") == "0.1.1"
    assert ur.next_patch_version("0.1") == "0.1.1"
    assert ur.next_patch_version("1.2.9") == "1.2.10"


def test_secret_scan() -> None:
    # Fixtures are built from split strings so the COMMITTED test file never
    # contains a literal secret-looking pattern (the release secret scan runs
    # over the allowlisted commit set, which includes this test file).
    import tempfile
    d = Path(tempfile.mkdtemp())
    ok = d / "ok.py"
    ok.write_text("print('hello world')\nAPI_URL = 'https://example.com'\n", encoding="utf-8")
    fake_token = "gh" + "p_" + "A" * 30
    bad = d / "bad.py"
    bad.write_text("token = '" + fake_token + "'\n", encoding="utf-8")
    fake_key_hdr = "-----BEGIN " + "PRIVATE KEY-----"
    key = d / "key.pem"
    key.write_text(fake_key_hdr + "\nAAAA\n" + fake_key_hdr.replace("BEGIN", "END") + "\n", encoding="utf-8")
    blockers, warns = ur.secret_scan([ok])
    assert not blockers and not warns  # clean file stays clean
    blockers, warns = ur.secret_scan([bad, key])
    assert len(blockers) >= 2


def test_package_zip_contains_frozen_build(ui_dir: Path, out_root: Path, tmp_path: Path) -> None:
    import zipfile
    ur.build(ui_dir, out_root, build_id="t1", git_sha="x", git_dirty=False,
             timestamp="2026-01-01T00:00:00Z")
    pkg = ur.package_ui_build(out_root / "t1", tmp_path / "pkgs", aivido_version="0.1.1", ui_version="1.0.0")
    assert pkg.is_file()
    with zipfile.ZipFile(pkg) as zf:
        names = set(zf.namelist())
    assert "ava.html" in names and "ui-version.json" in names
    # hash parity: unzip and compare against the frozen build
    with zipfile.ZipFile(pkg) as zf:
        zf.extractall(tmp_path / "x")
    for rel in ("ava.html", "ava.css", "ava.js", "ui-version.json"):
        assert ur.sha256_file(tmp_path / "x" / rel) == ur.sha256_file(out_root / "t1" / rel)


def test_release_commit_allowlist(tmp_path: Path) -> None:
    # hermetic scratch git repo: a release commit must touch ONLY allowlisted files
    import subprocess
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(repo), check=True)
    ui = repo / "ui"
    ui.mkdir()
    for rel, text in CANONICAL_FILES.items():
        (ui / rel).write_text(text, encoding="utf-8")
    (repo / "scripts").mkdir()
    (repo / "scripts" / "ui_release.py").write_text("# release tool\n", encoding="utf-8")
    (repo / "config").mkdir()
    (repo / "config" / "ui_release.json").write_text("{}\n", encoding="utf-8")
    (repo / "unrelated.txt").write_text("dirty work\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=str(repo), check=True)
    # dirty work appears AFTER the base commit
    (repo / "unrelated.txt").write_text("dirty work v2\n", encoding="utf-8")
    (repo / "ui" / "ava.html").write_text(CANONICAL_FILES["ava.html"] + "<!-- v2 -->", encoding="utf-8")
    cfg = {
        "canonical_ui_dir": "ui",
        "release": {"commit_paths": ["ui", "scripts/ui_release.py", "config/ui_release.json"]},
    }
    files = ur.release_commit_files(cfg, root=repo)
    paths = [p.relative_to(repo).as_posix() for p in files]
    assert "ui/ava.html" in paths and "scripts/ui_release.py" in paths
    assert "unrelated.txt" not in paths
    subprocess.run(["git", "add", "--", *paths], cwd=str(repo), check=True)
    staged = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=str(repo),
                            capture_output=True, text=True, check=True).stdout.splitlines()
    assert "unrelated.txt" not in staged
    assert "ui/ava.html" in staged
    subprocess.run(["git", "commit", "-qm", "Aivido UI Release 1.0.0 (t1)"], cwd=str(repo), check=True)
    # unrelated.txt remains uncommitted dirty work
    st = subprocess.run(["git", "status", "--porcelain"], cwd=str(repo), capture_output=True, text=True, check=True)
    assert "unrelated.txt" in st.stdout


def test_cache_bust_rewrite(ui_dir: Path, out_root: Path) -> None:
    ur.build(ui_dir, out_root, build_id="t1", git_sha="x", git_dirty=False,
             timestamp="2026-01-01T00:00:00Z")
    html = (out_root / "t1" / "ava.html").read_text(encoding="utf-8")
    for name in ("ava.css", "ava.js", "ava_widget.js"):
        want = ur.sha8((out_root / "t1" / name).read_text(encoding="utf-8"))
        assert f"/static/{name}?v={want}" in html
    # stale hardcoded versions are gone
    assert "?v=7" not in html
    assert "?v=3" not in html


def test_build_manifest_matches_files(ui_dir: Path, out_root: Path) -> None:
    ur.build(ui_dir, out_root, build_id="t1", git_sha="x", git_dirty=False,
             timestamp="2026-01-01T00:00:00Z")
    checks = ur.verify_build_local(out_root / "t1", quiet=True)
    assert all(c["ok"] for c in checks), [c for c in checks if not c["ok"]]
    # cache-bust checks exist for all three routes
    names = [c["name"] for c in checks]
    assert any("cache-bust / " in n for n in names)      # route "" -> /
    assert any("cache-bust app " in n for n in names)
    assert any("cache-bust dev " in n for n in names)


# ---------------------------------------------------------------- deploy ---
def test_deploy_copy_only_and_backup(ui_dir: Path, out_root: Path, backup_root: Path, tmp_path: Path) -> None:
    ur.build(ui_dir, out_root, build_id="t1", git_sha="x", git_dirty=False,
             timestamp="2026-01-01T00:00:00Z")
    target = tmp_path / "deployed_ui"
    target.mkdir()
    (target / "keepme.txt").write_text("unrelated", encoding="utf-8")
    (target / "legacy.zip").write_bytes(b"junk")
    # pre-existing file that will be overwritten
    (target / "ava.html").write_text("old version", encoding="utf-8")

    ur.deploy_build(out_root / "t1", target, backup_root)
    # unrelated files preserved
    assert (target / "keepme.txt").read_text(encoding="utf-8") == "unrelated"
    assert (target / "legacy.zip").read_bytes() == b"junk"
    # overwritten file is the build's version
    assert (target / "ava.html").read_bytes() == (out_root / "t1" / "ava.html").read_bytes()
    # ui-version.json + manifest present
    assert (target / "ui-version.json").is_file()
    # backup recorded the pre-deploy state
    rec = json.loads((backup_root / "t1" / "deploy-record.json").read_text(encoding="utf-8"))
    assert rec["backed_up"]["ava.html"] == ur.sha256_bytes(b"old version")


def test_deploy_dry_run_writes_nothing(ui_dir: Path, out_root: Path, backup_root: Path, tmp_path: Path) -> None:
    ur.build(ui_dir, out_root, build_id="t1", git_sha="x", git_dirty=False,
             timestamp="2026-01-01T00:00:00Z")
    target = tmp_path / "deployed_ui"
    target.mkdir()
    (target / "ava.html").write_text("original", encoding="utf-8")
    r = ur.deploy_build(out_root / "t1", target, backup_root, dry_run=True)
    assert r["dry_run"]
    assert (target / "ava.html").read_text(encoding="utf-8") == "original"
    assert not (backup_root / "t1").exists()


def test_rollback_exact(ui_dir: Path, out_root: Path, backup_root: Path, tmp_path: Path) -> None:
    ur.build(ui_dir, out_root, build_id="t1", git_sha="x", git_dirty=False,
             timestamp="2026-01-01T00:00:00Z")
    ur.build(ui_dir, out_root, build_id="t2", git_sha="x", git_dirty=False,
             timestamp="2026-01-01T00:00:01Z")
    target = tmp_path / "deployed_ui"
    target.mkdir()
    (target / "ava.html").write_text("original", encoding="utf-8")
    (target / "keepme.txt").write_text("keep", encoding="utf-8")

    ur.deploy_build(out_root / "t1", target, backup_root)
    assert (target / "ava.html").read_bytes() == (out_root / "t1" / "ava.html").read_bytes()
    assert (target / "ui-version.json").is_file()
    ur.deploy_build(out_root / "t2", target, backup_root)
    assert (target / "ava.html").read_bytes() == (out_root / "t2" / "ava.html").read_bytes()

    # rollback to the first deploy record
    ur.rollback(target, backup_root, "t1")
    assert (target / "ava.html").read_text(encoding="utf-8") == "original"
    # build-only file introduced by deploy t1 (ui-version.json) is removed
    assert not (target / "ui-version.json").exists()
    assert (target / "keepme.txt").read_text(encoding="utf-8") == "keep"


def test_rollback_latest_and_dry_run(ui_dir: Path, out_root: Path, backup_root: Path, tmp_path: Path) -> None:
    ur.build(ui_dir, out_root, build_id="t1", git_sha="x", git_dirty=False,
             timestamp="2026-01-01T00:00:00Z")
    target = tmp_path / "deployed_ui"
    target.mkdir()
    (target / "ava.html").write_text("original", encoding="utf-8")
    ur.deploy_build(out_root / "t1", target, backup_root)
    r = ur.rollback(target, backup_root, dry_run=True)
    assert r["dry_run"]
    assert (target / "ava.html").read_bytes() == (out_root / "t1" / "ava.html").read_bytes()
    ur.rollback(target, backup_root)
    assert (target / "ava.html").read_text(encoding="utf-8") == "original"


# ------------------------------------------------------------- live verify ---
def _free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_staging_server(build_dir: Path, backend: str = "http://127.0.0.1:1") -> tuple:
    port = _free_port()
    code = (
        "import sys,json;"
        f"sys.path.insert(0,{json.dumps(str(SCRIPTS))});"
        f"from ui_staging_server import create_app;"
        "import uvicorn;"
        f"uvicorn.run(create_app({json.dumps(str(build_dir))},{json.dumps(backend)}),"
        f"host='127.0.0.1',port={port},log_level='error')"
    )
    proc = subprocess.Popen([sys.executable, "-c", code], cwd=str(ROOT))
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        if proc.poll() is not None:
            raise RuntimeError(f"staging server exited early ({proc.returncode})")
        try:
            import urllib.request
            with urllib.request.urlopen(f"{base}/healthz", timeout=1) as r:
                if r.status == 200:
                    return proc, base
        except Exception:
            time.sleep(0.1)
    proc.terminate()
    raise RuntimeError("staging server did not come up")


@pytest.fixture()
def built(ui_dir: Path, out_root: Path):
    ur.build(ui_dir, out_root, build_id="live1", git_sha="feedface", git_dirty=False,
             timestamp="2026-01-01T00:00:00Z")
    return out_root / "live1"


def test_verify_target_route_and_hash_parity(built: Path) -> None:
    proc, base = _start_staging_server(built)
    try:
        checks = ur.verify_target([base], built, timeout=5.0, quiet=True)
        assert all(c["ok"] for c in checks), [c for c in checks if not c["ok"]]
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_verify_target_detects_tamper(built: Path) -> None:
    proc, base = _start_staging_server(built)
    try:
        (built / "ava.css").write_text("body{color:red} /* tampered */", encoding="utf-8")
        checks = ur.verify_target([base], built, timeout=5.0, quiet=True)
        asset = [c for c in checks if "asset hash parity" in c["name"]]
        assert asset and not asset[0]["ok"]
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_verify_cross_target_parity(built: Path) -> None:
    proc1, base1 = _start_staging_server(built)
    proc2, base2 = _start_staging_server(built)
    try:
        checks = ur.verify_target([base1, base2], built, timeout=5.0, quiet=True)
        assert all(c["ok"] for c in checks)
        names = [c["name"] for c in checks]
        assert any("cross-target parity" in n for n in names)
    finally:
        proc1.terminate()
        proc2.terminate()
        proc1.wait(timeout=10)
        proc2.wait(timeout=10)


def test_verify_local_fails_on_corrupt_build(ui_dir: Path, out_root: Path) -> None:
    ur.build(ui_dir, out_root, build_id="bad", git_sha="x", git_dirty=False,
             timestamp="2026-01-01T00:00:00Z")
    (out_root / "bad" / "ava.js").write_text("corrupted", encoding="utf-8")
    checks = ur.verify_build_local(out_root / "bad", quiet=True)
    assert any(not c["ok"] for c in checks)


def test_runtime_pass_nonblocking(ui_dir: Path, out_root: Path, backup_root: Path, tmp_path: Path) -> None:
    """A broken/unconfigured runtime target must NEVER fail or roll back the
    public release — it is reported as AUTH_REQUIRED/OFFLINE/FAILED instead."""
    ur.build(ui_dir, out_root, build_id="rt1", git_sha="x", git_dirty=False,
             timestamp="2026-01-01T00:00:00Z")
    target_ui = tmp_path / "target_ui"
    target_ui.mkdir()
    (target_ui / "ava.html").write_text("old", encoding="utf-8")
    (target_ui / "keepme.txt").write_text("keep", encoding="utf-8")
    cfg = {
        "build_root": str(out_root),
        "backup_root": str(backup_root),
        "targets": {
            "shadow": {"type": "local", "ui_dir": str(target_ui)},
            "mac": {"type": "ssh", "host": "100.98.38.52", "user": "", "ui_dir": ""},
        },
        "release": {},
    }
    results = ur.runtime_pass(cfg, "rt1")
    states = {r["name"]: r["state"] for r in results}
    assert states["shadow"] == "UPDATED"
    assert states["mac"] == "AUTH_REQUIRED"
    # local target actually updated, unrelated file preserved
    assert (target_ui / "ava.html").read_bytes() == (out_root / "rt1" / "ava.html").read_bytes()
    assert (target_ui / "keepme.txt").read_text(encoding="utf-8") == "keep"


def test_update_flow_hermetic(ui_dir: Path, out_root: Path, tmp_path: Path, monkeypatch) -> None:
    """End-to-end portable updater: fake public source -> download -> verify ->
    backup -> atomic install -> health check. All loopback, no GitHub needed."""
    import http.server
    import socket
    import threading
    import urllib.request

    ur.build(ui_dir, out_root, build_id="pub1", aivido_version="0.1.1", git_sha="x",
             git_dirty=False, timestamp="2026-01-01T00:00:00Z")
    build_dir = out_root / "pub1"
    public_dir = tmp_path / "public"
    public_dir.mkdir()
    # serve the fake public source: ui-version.json + the release package zip
    for f in ("ui-version.json", "build-manifest.json"):
        (public_dir / f).write_bytes((build_dir / f).read_bytes())
    pkg = ur.package_ui_build(build_dir, tmp_path / "pkgs", aivido_version="0.1.1", ui_version="1.0.0")
    (public_dir / pkg.name).write_bytes(pkg.read_bytes())

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    class _DirHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(public_dir), **kw)

        def log_message(self, fmt, *args):
            pass  # keep pytest output clean

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), _DirHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        cfg = {
            "release": {"raw_ui_version_url": f"{base}/ui-version.json"},
            "targets": {"shadow": {"base_url": ""}},
        }
        monkeypatch.setattr(ur, "latest_release_asset_url", lambda c: (True, f"{base}/{pkg.name}"))

        # install target: a copy of the canonical ui with an OLD version marker
        target_ui = tmp_path / "installed_ui"
        target_ui.mkdir()
        for rel, text in CANONICAL_FILES.items():
            (target_ui / rel).write_text(text, encoding="utf-8")
        (target_ui / "userdata.txt").write_text("my config — never touched", encoding="utf-8")

        has, local, pub = ur.update_check(cfg, target_ui)
        assert pub and pub["build_id"] == "pub1"
        assert has is True  # local canonical differs from pub1

        backup_root = tmp_path / "bk"
        ok, detail = ur.update_runtime_install(cfg, target_ui, backup_root)
        assert ok, detail
        assert (target_ui / "userdata.txt").read_text(encoding="utf-8") == "my config — never touched"
        assert (target_ui / "ui-version.json").read_text(encoding="utf-8") == \
            (build_dir / "ui-version.json").read_text(encoding="utf-8")
        # already up to date now
        ok2, detail2 = ur.update_runtime_install(cfg, target_ui, backup_root)
        assert ok2 and "already up to date" in detail2
    finally:
        srv.shutdown()


def test_installations_registry_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ur, "INSTALLATIONS_FILE", tmp_path / "inst.json")
    ur.save_installations([{"name": "mac", "type": "ssh", "host": "100.98.38.52",
                            "user": "armin", "ui_dir": "/Users/armin/Unreal-Agent/ui"}])
    got = ur.load_installations()
    assert got[0]["name"] == "mac" and got[0]["host"] == "100.98.38.52"


def test_stage_pointer(ui_dir: Path, out_root: Path, tmp_path: Path) -> None:
    ur.build(ui_dir, out_root, build_id="t1", git_sha="x", git_dirty=False,
             timestamp="2026-01-01T00:00:00Z")
    staging = tmp_path / "staging"
    ur.stage(out_root, staging, "t1")
    assert ur.current_staged_build(staging) == "t1"
    rec = json.loads((staging / "staging.json").read_text(encoding="utf-8"))
    assert rec["build_id"] == "t1"
    assert set(rec["routes"]) == {"", "app", "dev"}