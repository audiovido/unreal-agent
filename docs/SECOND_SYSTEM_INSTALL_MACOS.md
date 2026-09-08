# Aivido V2.0.0 — Second-System Install Guide (macOS)

This guide installs and validates Aivido V2.0.0 on a **completely
different macOS machine** (a second system that has never run Aivido
before). It covers everything a fresh Mac needs, and ends with a
one-command acceptance run that proves the installation works
end-to-end.

> Use `scripts/acceptance/run_second_system_acceptance.sh` for the
> automated, evidence-backed acceptance pass. Use the manual steps
> below when you want to drive the install yourself.

---

## 1. Supported macOS version

- **macOS 12 (Monterey) or newer** (Intel or Apple Silicon).
- **bash 3.2+** (ships with macOS) or **zsh** — the installer and
  acceptance runner are POSIX shell scripts; no PowerShell, no
  Windows registry, no developer environment.
- No administrative rights are required for normal use. The installer
  and runner never elevate.

## 2. Required Unreal Engine version

- **Unreal Engine 5.x** (5.0 or newer; 5.8 is the certified development
  target). Earlier major versions (4.x) are not supported.
- Install it with the **Epic Games Launcher** so the engine lands in a
  standard location. The installer and acceptance runner detect engines
  in these locations (read-only, no fixed version assumed):

  - `/Users/Shared/Epic Games/UE_*`
  - `/Applications/Epic Games/UE_*`
  - `/Applications/UE_*` (manual installs)

- If your engine lives somewhere else, point the runner at it
  explicitly:

  ```bash
  UNREAL_AGENT_ENGINE_DIR=/Volumes/SSD/UE_5.8 \
    ./scripts/acceptance/run_second_system_acceptance.sh \
      --package /path/to/Aivido-V2.0.0-macOS
  ```

  or pass `--unreal-exe /path/to/UE_5.8/Engine/Binaries/Mac/UnrealEditor`.

## 3. Python and runtime handling

- **Python 3.9 or newer** is required (3.11/3.12 recommended). Install
  it from https://www.python.org/downloads/ or with Homebrew:

  ```bash
  brew install python@3.12
  ```

- The installer creates a **package-local `.venv`** next to the package;
  the acceptance runner creates its own **fully isolated temporary
  environment** so a failed acceptance run never dirties the real
  install.
- Runtime dependencies are declared in **`requirements.txt`** (fastapi,
  uvicorn, pillow, numpy, pydantic, requests, rich) and installed by pip
  from PyPI — the machine needs internet access during install only.

## 4. Hardware assumptions

- **Disk:** ~2 GB free for the runtime environment plus whatever the
  Unreal project needs.
- **RAM:** 16 GB recommended (the editor plus the backend run side by
  side).
- **GPU:** any GPU the Unreal Editor itself supports; the viewport must
  be able to render for evidence captures.
- **CPU:** 4+ cores recommended.

## 5. Ports

| Port | Owner                     | Purpose                              |
|------|---------------------------|--------------------------------------|
| 8765 | Aivido backend (uvicorn)  | REST API + web UI (fixed by product) |
| 6766 | Unreal bridge (in editor) | editor automation bridge             |
| 8844 | MCP gateway (optional)    | external tooling gateway             |

- All services bind to **127.0.0.1** (localhost only).
- The backend port **8765 is fixed** by the certified product; the bridge
  port can be moved with `UA_BRIDGE_PORT` (see §7).

## 6. Firewall notes

- Because everything binds to `127.0.0.1`, **no inbound firewall rule is
  required** for local use.
- If you expose the UI to another machine (Tailscale), allow only the
  Tailscale interface; never open 8765 to the public internet.

## 7. Environment variables

| Variable                  | Purpose                                            |
|---------------------------|----------------------------------------------------|
| `AIVIDO_HOME`             | package root override (defaults to the package)    |
| `AIVIDO_PYTHON`           | explicit Python interpreter override               |
| `UNREAL_AGENT_ENGINE_DIR` | explicit Unreal engine root override               |
| `AIVIDO_UNREAL_SCAN_DIRS` | os.pathsep-separated scan dirs for UE detection    |
| `UA_BRIDGE_PORT`          | bridge port override (default 6766)                |
| `UA_DISABLE_WORKBOARD_AUTOPILOT` | multi-client instance guard (set by tests)  |

## 8. Manual install

```bash
cd /path/to/Aivido-V2.0.0-macOS
./install-aivido.sh
```

What happens:

1. finds a Python 3.9+ interpreter
2. creates the package-local `.venv`
3. installs `requirements.txt` (only when needed — idempotent)
4. validates the runtime import contract
5. detects the Unreal Editor build (read-only scan of the locations in
   §2, or `UNREAL_AGENT_ENGINE_DIR`)
6. detects / selects a `.uproject` (recent project first, then scan)
7. starts the persistent backend on `127.0.0.1:8765`
8. opens the Aivido UI at http://127.0.0.1:8765/app

## 9. Runtime control

```bash
./start-aivido.sh start      # start persistent backend
./start-aivido.sh stop       # stop backend (bridge/gateway untouched)
./start-aivido.sh restart    # stop then start
./start-aivido.sh status     # state + health + log paths
./start-aivido.sh doctor     # full self-test (PASS/WARN/FAIL)
```

## 10. Automated acceptance

```bash
./scripts/acceptance/run_second_system_acceptance.sh \
    --package /path/to/Aivido-V2.0.0-macOS
```

With a pinned project/map and explicit report path:

```bash
./scripts/acceptance/run_second_system_acceptance.sh \
    --package /path/to/Aivido-V2.0.0-macOS \
    --expected-project AividoHQ \
    --expected-map /Game/Maps/AividoHQ \
    --output /tmp/aivido-acceptance.json
```

The 20 phases mirror the Windows acceptance contract:

1. package integrity       11. verify active map
2. isolated runtime env    12. verify UI HTTP
3. install runtime deps    13. run doctor
4. validate python/runtime 14. one READ-ONLY mission
5. detect Unreal install   15. terminal mission result
6. UE version >= 5 gate    16. fresh screenshot/evidence
7. start backend           17. no stale evidence
8. backend health          18. clean restart
9. bridge availability     19. machine-readable JSON report
10. project identity       20. cleanup only its own processes

The mission is strictly read-only: no actor spawns, no level save —
only the transient proof PNG is written to the editor's
`Saved/UnrealAgent/` directory.

### Hermetic (mock) testing

To validate the runner itself without any live Unreal editor:

```bash
./scripts/acceptance/run_second_system_acceptance.sh \
    --package /path/to/Aivido-V2.0.0-macOS --mock
```

Scenarios: `success`, `python-runtime-fail`, `dep-install-fail`,
`unreal-missing`, `unsupported-version`, `port-collision`,
`backend-fail`, `bridge-down`, `wrong-project`, `wrong-map`,
`ui-down`, `doctor-fail`, `mission-timeout`, `mission-fail`,
`stale-evidence`, `screenshot-invalid`, `restart-fail`.

## 11. Speech availability

Aivido's optional chat speech is a MetaHuman/AvaLive feature that
requires the live editor bridge. On a second system where that resource
is unavailable, speech reports **unavailable/skipped** — it never fakes
success and never blocks startup.

## 12. Troubleshooting

| Symptom                                  | Fix                                                        |
|------------------------------------------|------------------------------------------------------------|
| `no usable Python (>= 3.9)`              | Install Python 3.9+ (python.org or `brew install python@3.12`) |
| `UNREAL_NOT_INSTALLED`                   | Install UE 5.x via Epic Launcher, or set `UNREAL_AGENT_ENGINE_DIR` |
| `UNSUPPORTED_UNREAL_VERSION`             | Aivido V2 requires UE 5.x                                   |
| `PORT_COLLISION` on 8765                 | Stop the process on 127.0.0.1:8765, then re-run            |
| `BRIDGE_UNAVAILABLE`                     | Open AividoHQ in the editor with the bridge on 127.0.0.1:6766 |
| backend unhealthy                        | See `config/logs/aivido_v1.err.log` in the package         |