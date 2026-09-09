param([string]$Path)
Add-Type -AssemblyName System.Drawing
$img = [System.Drawing.Image]::FromFile($Path)
$bmp = New-Object System.Drawing.Bitmap($img)
$total = 0.0; $n = 0
$hist = @{}
for ($x = 0; $x -lt $bmp.Width; $x += 4) {
    for ($y = 0; $y -lt $bmp.Height; $y += 4) {
        $c = $bmp.GetPixel($x, $y)
        $total += ($c.R * 0.299 + $c.G * 0.587 + $c.B * 0.114)
        $n++
        $key = ("{0:X2}{1:X2}{2:X2}" -f $c.R, $c.G, $c.B)
        if ($hist.ContainsKey($key)) { $hist[$key]++ } else { $hist[$key] = 1 }
    }
}
$avg = [math]::Round($total / $n, 1)
Write-Output ("SIZE {0}x{1} meanLuma={2}" -f $img.Width, $img.Height, $avg)
$top = $hist.GetEnumerator() | Sort-Object Value -Descending | Select-Object -First 5
foreach ($e in $top) { Write-Output ("  #{0} count={1}" -f $e.Key, $e.Value) }
$bmp.Dispose(); $img.Dispose()