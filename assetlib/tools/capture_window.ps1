param(
    [Parameter(Mandatory = $true)][string]$ProcessName,
    [Parameter(Mandatory = $true)][string]$OutFile,
    [string]$TitleMatch = "",
    [int]$WaitSeconds = 1
)

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32 {
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool GetWindowText(IntPtr hWnd, System.Text.StringBuilder text, int count);
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
}
"@

$cands = Get-Process -Name $ProcessName -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowHandle -ne 0 }
if ($TitleMatch -ne "") {
    $cands = $cands | Where-Object { $_.MainWindowTitle -like $TitleMatch }
}
$proc = $cands | Select-Object -First 1

if (-not $proc) {
    Write-Output ("CAPTURE_RESULT: no window found for " + $ProcessName + " title=" + $TitleMatch)
    exit 2
}

$handle = $proc.MainWindowHandle
$title = New-Object System.Text.StringBuilder 512
[Win32]::GetWindowText($handle, $title, 512) | Out-Null
[Win32]::SetForegroundWindow($handle) | Out-Null
Start-Sleep -Milliseconds ($WaitSeconds * 1000)

$rect = New-Object Win32+RECT
[Win32]::GetWindowRect($handle, [ref]$rect) | Out-Null
$w = $rect.Right - $rect.Left
$h = $rect.Bottom - $rect.Top
if ($w -le 0 -or $h -le 0) {
    Write-Output "CAPTURE_RESULT: invalid window rect"
    exit 3
}

Add-Type -AssemblyName System.Drawing
$bmp = New-Object System.Drawing.Bitmap($w, $h)
$gfx = [System.Drawing.Graphics]::FromImage($bmp)
$gfx.CopyFromScreen($rect.Left, $rect.Top, 0, 0, (New-Object System.Drawing.Size($w, $h)))
$bmp.Save($OutFile, [System.Drawing.Imaging.ImageFormat]::Png)
$gfx.Dispose()
$bmp.Dispose()

$len = (Get-Item $OutFile).Length
Write-Output ("CAPTURE_RESULT: ok rect=" + $rect.Left + "," + $rect.Top + "," + $w + "x" + $h + " title=" + $title.ToString() + " bytes=" + $len + " file=" + $OutFile)
exit 0
