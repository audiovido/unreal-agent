"""Dismiss modal 'Message' dialogs blocking the Unreal editor."""
Add-Type @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class WinEnum {
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc cb, IntPtr lp);
    [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder sb, int max);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint msg, IntPtr wp, IntPtr lp);
    public delegate bool EnumWindowsProc(IntPtr h, IntPtr lp);
    public static List<IntPtr> Find(uint targetPid, string title) {
        var found = new List<IntPtr>();
        EnumWindows((h, lp) => {
            uint pid; GetWindowThreadProcessId(h, out pid);
            if (pid == targetPid && IsWindowVisible(h)) {
                var sb = new StringBuilder(256); GetWindowText(h, sb, 256);
                if (sb.ToString() == title) found.Add(h);
            }
            return true;
        }, IntPtr.Zero);
        return found;
    }
}
"@
$proc = Get-Process UnrealEditor | Select-Object -First 1
$handles = [WinEnum]::Find([uint32]$proc.Id, "Message")
Write-Output "found $($handles.Count) Message dialogs"
foreach ($h in $handles) {
    [WinEnum]::PostMessage($h, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
    Write-Output "WM_CLOSE sent to $h"
}
Start-Sleep -Seconds 3
$still = [WinEnum]::Find([uint32]$proc.Id, "Message")
Write-Output "remaining: $($still.Count)"
