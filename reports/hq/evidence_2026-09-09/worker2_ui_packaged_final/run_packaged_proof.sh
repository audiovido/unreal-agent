#!/usr/bin/env bash
# Packaged-build validation driver v6 (deterministic termination).
#
# Root causes fixed across v3-v6:
#  1. Backgrounded capture subshells inherited the tool's stdout pipe; a hung
#     capture kept the pipe open after bash exited and the outer tool blocked
#     on EOF forever. ALL capture output is redirected to a log file.
#  2. A hung Win32 CopyFromScreen/SetForegroundWindow call can block a capture
#     indefinitely. Every capture is wrapped in GNU `timeout 10` so the
#     process group is killed externally.
#  3. The game process owns TWO top-level windows (stale bootstrap + real game
#     window) and Process.MainWindowHandle flips between them. capture_window.ps1
#     therefore EnumWindows across all PIDs and filters by title/visibility/size.
#
# The driver: launches the packaged game with -AividoAutoProof, breaks on the
# final "AIVIDO_PROOF: done" marker, hard 60s deadline, sweeps stray game
# processes at the end. Optional env overrides: RESX/RESY/SUFFIX.
set -u
RESX="${RESX:-1280}"
RESY="${RESY:-720}"
SUFFIX="${SUFFIX:-}"
PKG="C:/Users/Shadow/AppData/Local/Temp/aivido-worker2-package/Windows"
LOG="C:/Users/Shadow/AppData/Local/Temp/aivido-worker2-package/proof_final.log"
CAPLOG="C:/Users/Shadow/AppData/Local/Temp/aivido-worker2-package/cap.log"
EVID="C:/Users/Shadow/Desktop/Unreal-Agent/.worktrees/aivido-worker2-ui/reports/hq/evidence_2026-09-09/worker2_ui_packaged_final"
CAPPS="$EVID/capture_window.ps1"
DEADLINE=$(( SECONDS + 60 ))

rm -f "$LOG" "$CAPLOG"
( cd "$PKG" && ./AividoV2Game.exe AividoHQ -game -windowed "-ResX=$RESX" "-ResY=$RESY" -AividoAutoProof -log "-AbsLog=C:\\Users\\Shadow\\AppData\\Local\\Temp\\aivido-worker2-package\\proof_final.log" > "exe_final$SUFFIX.txt" 2>&1 & )

cap() {
  timeout 10 powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$CAPPS" -OutPath "$1" -RetrySeconds 6 >> "$CAPLOG" 2>&1
}

state=boot
result=TIMEOUT
while [ $SECONDS -lt $DEADLINE ]; do
  sleep 0.4
  [ -f "$LOG" ] || continue
  if grep -q "AIVIDO_PROOF: done" "$LOG" 2>/dev/null; then result=COMPLETE; break; fi
  if [ "$state" = boot ] && grep -q "AIVIDO_PROOF: begin" "$LOG" 2>/dev/null; then
    state=menu
    { sleep 0.7; cap "$EVID/01_main_menu$SUFFIX.png"; } > /dev/null 2>&1 &
  elif [ "$state" = menu ] && grep -q "AIVIDO_PROOF: walk_end" "$LOG" 2>/dev/null; then
    state=pause
    { sleep 1.0; cap "$EVID/03_gameplay_hud$SUFFIX.png"; } > /dev/null 2>&1 &
    { sleep 2.2; cap "$EVID/02_pause_menu$SUFFIX.png"; } > /dev/null 2>&1 &
  elif [ "$state" = pause ] && grep -q "AIVIDO_PROOF: conv_open" "$LOG" 2>/dev/null; then
    state=conv
    { sleep 1.4; cap "$EVID/04_conversation$SUFFIX.png"; } > /dev/null 2>&1 &
  elif [ "$state" = conv ] && grep -q "AIVIDO_PROOF: restored_camera" "$LOG" 2>/dev/null; then
    state=restored
    { sleep 0.5; cap "$EVID/05_gameplay_restored$SUFFIX.png"; } > /dev/null 2>&1 &
  fi
done

sleep 14   # bounded window for the trailing background captures

echo "RESULT=$result state=$state elapsed=${SECONDS}s"
echo "=====PROOF LINES====="
grep -E "AIVIDO_PROOF|AIVIDO_STATE|AIVIDO_UI" "$LOG" 2>/dev/null | head -40
echo "=====ISSUES (ensure/assert/fatal)====="
grep -cE "Ensure condition failed|Assertion failed|Fatal error|LogWindows: Error" "$LOG" 2>/dev/null || echo 0
echo "=====CAPTURE LOG====="
cat "$CAPLOG" 2>/dev/null
echo "=====CAPTURE FILES====="
ls -la "$EVID"/*"$SUFFIX.png" 2>/dev/null || echo "none"

# Sweep: the proof is deterministic (ends at 'done'); kill any leftover game.
powershell.exe -NoProfile -Command "Get-Process AividoV2Game -ErrorAction SilentlyContinue | Stop-Process -Force" > /dev/null 2>&1
exit 0
