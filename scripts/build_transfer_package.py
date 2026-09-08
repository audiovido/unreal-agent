"""Assemble V2 release files, certified tooling, and portability fixes.

Run with --out pointing to an empty output directory.
"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RELEASE = 'eb466133f91d553c325d97b99ab93627dfd4aade'
TOOLING = '9eaccee8656973e905deeb589fb65f619facae9b'
EXTRA = ['scripts/acceptance/run_second_system_acceptance.ps1',
         'scripts/acceptance/second_system_checks.py',
         'docs/SECOND_SYSTEM_INSTALL.md',
         'reports/templates/AIVIDO_SECOND_SYSTEM_ACCEPTANCE_TEMPLATE.json']
PORTABILITY_FILES = [
    'core/portable_paths.py', 'app/speak.py', 'app/proof.py', 'app/api.py',
    'core/orchestrator.py', 'tools/unreal/project_context.py',
    'tools/unreal/project_manager.py', 'tools/system/tool_runner.py',
    'scripts/aivido_install_check.py', 'ui/aivido.js', 'ui/devboard.html',
    'ui/product.html', 'config/settings.json',
]
ENTRY = ['requirements.txt', 'install-aivido.ps1', 'install-aivido.cmd',
         'start-aivido.ps1', 'start-aivido.cmd', 'stop-aivido.cmd',
         'config/settings.json']
SCRIPTS = ['scripts/aivido_' + x + '.py' for x in
           ['runtime', 'watchdog', 'doctor', 'smoke', 'install_check']]

def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])

def build(out):
    assert git('rev-parse', 'v2.0.0^{commit}').decode().strip() == RELEASE
    out.mkdir(parents=True, exist_ok=True)
    target = out / 'Aivido-V2.0.0-Windows.zip'
    if target.exists():
        raise FileExistsError(target)
    tracked = git('ls-tree', '-r', '--name-only', RELEASE).decode().splitlines()
    selected = set(ENTRY + SCRIPTS)
    for name in tracked:
        p = Path(name)
        if p.parts[0] in ('app', 'core', 'tools', 'blender_agent', 'qa') and p.suffix == '.py' and name != 'app/mcp_gateway.py':
            selected.add(name)
        if p.parts[0] == 'ui' and len(p.parts) == 2 and p.suffix in ('.html', '.js', '.css', '.json', '.txt') and not any(x in name for x in ('backup-', '.broken-encoding', '.agentboard_backup')):
            selected.add(name)
    files = {n: git('show', RELEASE + ':' + n) for n in sorted(selected)}
    files.update({n: git('show', TOOLING + ':' + n) for n in EXTRA})
    files.update({n: (ROOT / n).read_bytes() for n in PORTABILITY_FILES})
    files['scripts/acceptance/transfer_package_smoke.py'] = (
        ROOT / 'scripts/acceptance/transfer_package_smoke.py').read_bytes()
    files['version.json'] = json.dumps({'product': 'Aivido', 'version': '2.0.0', 'sha': RELEASE, 'source_tag': 'v2.0.0', 'second_system_tooling_sha': TOOLING, 'entrypoint': 'install-aivido.ps1'}, indent=2).encode()
    files['README-QUICKSTART.md'] = b'# Aivido V2.0.0 Windows\n\nInstall Python 3.9+ and run install-aivido.cmd. The installer creates a new local .venv and installs requirements.txt from PyPI. See docs/SECOND_SYSTEM_INSTALL.md for prerequisites and acceptance instructions.\n'
    manifest = {n: hashlib.sha256(b).hexdigest() for n, b in sorted(files.items())}
    files['manifest.json'] = json.dumps({'version': '2.0.0', 'source_release_sha': RELEASE, 'source_tag': 'v2.0.0', 'second_system_tooling_sha': TOOLING, 'portability_files': PORTABILITY_FILES, 'files_sha256': manifest}, indent=2).encode()
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo('Aivido-V2.0.0-Windows/' + name, (2026, 9, 7, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (out / 'Aivido-V2.0.0-Windows.sha256.txt').write_text(digest + '  ' + target.name + '\n', encoding='ascii')
    print(json.dumps({'zip_path': str(target.resolve()), 'zip_size': target.stat().st_size, 'zip_sha256': digest, 'file_count': len(files)}, indent=2))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    build(parser.parse_args().out)
