# Aivido V2 — Second-System Install Guide

This guide installs and validates Aivido V2 on a **completely different
Windows machine** (a second system that has never run Aivido before). It
covers everything a fresh PC needs, and ends with a one-command acceptance
run that proves the installation works end-to-end.

> Use `scripts/acceptance/run_second_system_acceptance.ps1` for the
> automated, evidence-backed acceptance pass. Use the manual steps below
> when you want to drive the install yourself.

---

## 1. Supported Windows version

- **Windows 10 64-bit** (version 22H2 or newer) or **Windows 11 64-bit**.
- Windows PowerShell **5.1** (ships with Windows) is used by the installer
  and the acceptance runner — nothing extra to install for that.
- Administrative rights are **not** required for normal use. The runner and
  installer never elevate.

## 2. Required Unreal Engine version

- **Unreal Engine 5.x** (5.0 or newer; 5.8 is the certified development
  target). Earlier major versions (4.x) are not supported.
- Install it with the **Epic Games Launcher** so the engine registers in
  `HKLM\SOFTWARE\EpicGames\Unreal Engine\Builds`. The installer and
  acceptance runner read that registry key to detect the engine.
- If your engine was installed without the launcher, point the acceptance
  runner at it explicitly:

  ```powershell
  powershell -ExecutionPolicy Bypass -File scripts\acceptance\run_second_system_acceptance.ps1 `
      -PackagePath "C:\Aivido\Aivido-V2" `
      -UnrealExePath "D:\Epic\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe"
  ```

## 3. Python and runtime handling

- **Python 3.9 or newer** is required (3.11/3.12 recommended). Install it
  from https://www.python.org/downloads/ and tick **"Add python.exe to
  PATH"** during install, or install the Microsoft Store Python.
- The installer creates a **local `.venv`** next to the package; the
  acceptance runner creates its own **fully isolated temporary environment**
  so a failed acceptance run never dirties the real install.
- Runtime dependencies are declared in **`requirements.txt`** (fastapi,
  uvicorn, pillow, numpy, pydantic, requests, rich) and installed by pip
  from PyPI — the machine needs internet access during install only.

## 4. Hardware assumptions

- **Disk:** ~2 GB free for the runtime environment plus whatever the
  Unreal project needs.
- **RAM:** 16 GB recommended (the editor plus the backend run side by side).
- **GPU:** any GPU the Unreal Editor itself supports; the viewport must be
  able to render for evidence captures.
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
- If a third-party firewall asks about `python.exe` or `uvicorn`, allow
  **private networks only**.

## 7. Environment variables

| Variable                | Default | Meaning                                            |
|-------------------------|---------|----------------------------------------------------|
| `UA_BRIDGE_PORT`        | `6766`  | Bridge port the editor listener binds on           |
| `UA_DISABLE_WORKBOARD_AUTOPILOT` | unset | Set to `1` to run a second instance without the workboard autopilot |
| `PYTHONUTF8`            | unset   | Optional; set to `1` if the machine's console encoding causes mojibake |

The acceptance runner also accepts overrides as parameters: `-BackendPort`,
`-BridgePort`, `-ExpectedProject`, `-ExpectedMap`, `-OutputPath`.

## 8. Package extraction / install

1. Copy the Aivido V2 package zip to the new machine and extract it, e.g.
   to `C:\Aivido\Aivido-V2`. The folder contains
   `install-aivido.ps1`, `start-aivido.ps1`, `requirements.txt`,
   `app\`, `core\`, `ui\`, `scripts\`, `version.json`.
2. One-click install + start + open UI:

   ```powershell
   cd C:\Aivido\Aivido-V2
   powershell -ExecutionPolicy Bypass -File .\install-aivido.ps1
   ```

   This checks Python, creates `.venv`, installs `requirements.txt` only
   when needed, validates the import contract, detects Unreal, selects the
   project, starts the persistent backend, and opens the UI. Re-running it
   is safe (idempotent).

## 9. Startup

```powershell
cd C:\Aivido\Aivido-V2
powershell -ExecutionPolicy Bypass -File .\start-aivido.ps1 start
```

or use `.\start-aivido.cmd`. The backend survives the terminal closing.

## 10. Shutdown

```powershell
powershell -ExecutionPolicy Bypass -File .\start-aivido.ps1 stop
```

or double-click `stop-aivido.cmd`. This stops only the Aivido backend; the
Unreal editor and bridge are left untouched.

## 11. Restart

```powershell
powershell -ExecutionPolicy Bypass -File .\start-aivido.ps1 restart
```

## 12. UI URL

Open **http://127.0.0.1:8765/app** in a browser on the machine. The status
command prints the live URL:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-aivido.ps1 status
```

## 13. Unreal connection

1. Open the **AividoHQ project** in Unreal Editor 5.x on the same machine.
2. Ensure the **Aivido bridge** is running inside the editor (the bridge
   listener on `127.0.0.1:6766`; `UA_BRIDGE_PORT` can move it).
3. Verify the connection from PowerShell:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\start-aivido.ps1 status
   ```

   The `bridge` line must read `listening=True`.

## 14. Doctor

```powershell
powershell -ExecutionPolicy Bypass -File .\start-aivido.ps1 doctor
# non-destructive against a live session:
powershell -ExecutionPolicy Bypass -File .\start-aivido.ps1 doctor -Quick
```

Every check prints `PASS / WARN / FAIL`; the exit code is non-zero when any
check fails.

## 15. First mission

The one-command acceptance runner (below) runs a **read-only** mission:
bridge ping, project identity, active map check, and a viewport capture.
It never spawns actors and never saves the level.

For a deeper real mission after install, the product smoke mission
exercises a bounded spawn/verify/delete cycle with a disposable actor:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-aivido.ps1 smoke
```

## 16. Evidence verification

- Captures are written to `<project>\Saved\UnrealAgent\viewport_latest.png`.
- The backend serves the freshest capture at **http://127.0.0.1:8765/api/proof/latest**.
- The acceptance runner verifies the served PNG is a valid, non-trivial,
  **freshly captured** image (byte-identical to the capture file from this
  run, and newer than the pre-run baseline).

## 17. One-command acceptance (recommended)

From the runner checkout on the second machine:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\acceptance\run_second_system_acceptance.ps1 `
    -PackagePath "C:\Aivido\Aivido-V2"
```

The runner performs 20 steps (validate package → isolated env → install
deps → validate runtime → detect Unreal → verify UE version → start backend
→ backend health → bridge → project identity → active map → UI HTTP →
doctor → read-only mission → terminal mission result → fresh evidence →
no stale evidence → clean restart → emit JSON → shutdown only its own
processes) and prints `SECOND_SYSTEM_ACCEPTANCE PASS/FAIL` with a full
report in `reports\second_system\<run_id>\acceptance.json`.

Useful flags:

```powershell
-ExpectedProject "AividoHQ"          # require this editor project
-ExpectedMap "/Game/Maps/AividoHQ"   # require this active map
-OutputPath "C:\Aivido\acceptance.json"
-MissionTimeoutSeconds 300           # slow editor? give the mission more time
-KeepLogs                            # keep the isolated env temp dir for forensics
```

## 18. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `UNREAL_NOT_INSTALLED` | Engine not in the Epic registry | Install via Epic Games Launcher, or pass `-UnrealExePath`. |
| `UNSUPPORTED_UNREAL_VERSION` | Engine is UE 4.x or unparseable | Install/point at UE 5.x. |
| `PYTHON_RUNTIME_FAILURE` | Python < 3.9 or not on PATH | Install Python 3.9+ with "Add to PATH". |
| `DEPENDENCY_INSTALL_FAILURE` | No PyPI access during pip install | Check network/proxy; see pip log in `reports\second_system\<run_id>\`. |
| `PORT_COLLISION` | Something else on 127.0.0.1:8765 | Stop the conflicting process, or a leftover Aivido backend. |
| `BACKEND_START_FAILURE` | Backend crashed at boot | Read `backend.err.log` in the report; usually a missing dependency. |
| `BRIDGE_UNAVAILABLE` | Editor closed or bridge not running | Open AividoHQ in UE 5.x and confirm the bridge listener on 6766. |
| `WRONG_UNREAL_PROJECT` | Wrong project open | Open the expected project, or pass `-ExpectedProject`. |
| `WRONG_ACTIVE_MAP` | Wrong map loaded | Open `/Game/Maps/AividoHQ`, or pass `-ExpectedMap`. |
| `UI_UNAVAILABLE` | Backend up but UI not served | Check the package includes `ui\`; re-extract. |
| `DOCTOR_FAILURE` | Doctor self-test found a real fault | Read `doctor.json` in the report and fix the flagged check. |
| `MISSION_TIMEOUT` | Editor busy/frozen | Let the editor idle; increase `-MissionTimeoutSeconds`. |
| `MISSION_FAILURE` | One mission step failed | See `mission.steps` in the report for the exact step. |
| `STALE_EVIDENCE` | Evidence not refreshed | Bring the editor viewport to the foreground (minimized editors can't capture). |
| `SCREENSHOT_INVALID` | Capture missing/bad PNG | Un-occlude the editor viewport and re-run. |
| `RESTART_FAILURE` | Stop/start cycle failed | Check backend logs; free port 8765; re-run. |
| `PACKAGE_INTEGRITY_FAILURE` | Package incomplete | Re-extract the zip; verify the missing files listed in the failure reason. |

### Still stuck?

Run the runner with `-KeepLogs` and send the whole
`reports\second_system\<run_id>\` folder (JSON report + logs) along with
the failing stage code. Every failure record includes the stage, the code,
a human-readable reason, and a suggested remediation — start from the
`failures` array in the acceptance JSON.