param(
    [string]$ProcessName = "AividoV2Game",
    [string]$OutPath,
    [string]$TitleMatch = "ASSET_Showcase2",
    [int]$RetrySeconds = 6
)
# OS window capture v7. The game process owns TWO top-level windows (a stale
# bootstrap window and the real game window); Process.MainWindowHandle flips
# between them, so we EnumWindows across ALL PIDs of the process name and pick
# the visible >=400x300 window whose title matches. Callers MUST wrap this in
# GNU `timeout` (a hung Win32 call can otherwise block forever).
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public struct RECT7 { public int Left; public int Top; public int Right; public int Bottom; }
public class W32G {
    public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lParam);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT7 rect);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder sb, int max);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
}
"@

$deadline = (Get-Date).AddSeconds($RetrySeconds)
$target = [IntPtr]::Zero
while ($target -eq [IntPtr]::Zero) {
    $pids = @(Get-Process -Name $ProcessName -ErrorAction SilentlyContinue | ForEach-Object { [uint32]$_.Id })
    foreach ($tp in $pids) {
        $script:hit = [IntPtr]::Zero
        $cb = [W32G+EnumProc]{
            param($h, $l)
            $wpid = [uint32]0
            [W32G]::GetWindowThreadProcessId($h, [ref]$wpid) | Out-Null
            if ($wpid -eq $tp) {
                $sb = New-Object System.Text.StringBuilder 256
                [W32G]::GetWindowText($h, $sb, 256) | Out-Null
                if ($sb.ToString() -like "*$TitleMatch*" -and [W32G]::IsWindowVisible($h)) {
                    $r = New-Object RECT7
                    [W32G]::GetWindowRect($h, [ref]$r) | Out-Null
                    if (($r.Right - $r.Left) -ge 400 -and ($r.Bottom - $r.Top) -ge 300) {
                        $script:hit = $h
                        return $false
                    }
                }
            }
            return $true
        }
        [W32G]::EnumWindows($cb, [IntPtr]::Zero) | Out-Null
        if ($script:hit -ne [IntPtr]::Zero) { $target = $script:hit; break }
    }
    if ($target -eq [IntPtr]::Zero) {
        if ((Get-Date) -gt $deadline) { Write-Output "NOCAPTURE no matching game window"; exit 2 }
        Start-Sleep -Milliseconds 400
    }
}

[W32G]::SetForegroundWindow($target) | Out-Null
Start-Sleep -Milliseconds 500
$r2 = New-Object RECT7
[W32G]::GetWindowRect($target, [ref]$r2) | Out-Null
$w2 = $r2.Right - $r2.Left; $h2 = $r2.Bottom - $r2.Top
if ($w2 -lt 400 -or $h2 -lt 300) { Write-Output "NOCAPTURE window shrank ${w2}x${h2}"; exit 2 }
$bmp = New-Object System.Drawing.Bitmap($w2, $h2)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($r2.Left, $r2.Top, 0, 0, $bmp.Size)
$bmp.Save($OutPath, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Output "CAPTURED $OutPath ${w2}x${h2}"