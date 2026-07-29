# Live side-by-side Ctrl+P compare: rxycode vs opencode
# Launches two consoles, sends Ctrl+P, captures screenshots.

$ErrorActionPreference = "Stop"
$outDir = "d:\agent-demo\RxyCode\RxyCode1_1_0\frontend\opentui-app\e2e\compare-shots"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public class Win {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr hWnd, int X, int Y, int W, int H, bool repaint);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
  public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
}
"@

function Get-WindowsForPid([int]$processId) {
  $found = New-Object System.Collections.Generic.List[IntPtr]
  $cb = [Win+EnumWindowsProc]{
    param($h,$l)
    if (-not [Win]::IsWindowVisible($h)) { return $true }
    [uint32]$wpid = 0
    [void][Win]::GetWindowThreadProcessId($h, [ref]$wpid)
    if ($wpid -eq $processId) { $found.Add($h) }
    return $true
  }
  [void][Win]::EnumWindows($cb, [IntPtr]::Zero)
  return $found
}

function Wait-MainWindow([System.Diagnostics.Process]$proc, [int]$timeoutMs = 15000) {
  $sw = [Diagnostics.Stopwatch]::StartNew()
  while ($sw.ElapsedMilliseconds -lt $timeoutMs) {
    $proc.Refresh()
    if ($proc.MainWindowHandle -ne [IntPtr]::Zero) { return $proc.MainWindowHandle }
    $wins = Get-WindowsForPid $proc.Id
    if ($wins.Count -gt 0) { return $wins[0] }
    Start-Sleep -Milliseconds 250
  }
  return [IntPtr]::Zero
}

function Capture-Screen([string]$path, [int]$x, [int]$y, [int]$w, [int]$h) {
  $bmp = New-Object System.Drawing.Bitmap $w, $h
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.CopyFromScreen($x, $y, 0, 0, (New-Object System.Drawing.Size($w, $h)))
  $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
  $g.Dispose(); $bmp.Dispose()
  Write-Host "SHOT $path"
}

# Screen halves
$screen = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
$halfW = [Math]::Floor($screen.Width / 2)
$h = $screen.Height
$leftX = $screen.X
$rightX = $screen.X + $halfW
$y = $screen.Y

# Kill leftover compare sessions if any (best-effort)
Get-Process -Name "rxycode","opencode" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500

$repo = "d:\agent-demo\RxyCode\RxyCode1_1_0"
$envBlock = "set RXYCODE_TUI=opentui&& set FORCE_COLOR=1&&"

# Launch left: rxycode
$pRxy = Start-Process -FilePath "cmd.exe" -ArgumentList "/k","$envBlock title RXYCODE_COMPARE&& cd /d `"$repo`"&& rxycode" -PassThru -WindowStyle Normal
# Launch right: opencode
$pOc = Start-Process -FilePath "cmd.exe" -ArgumentList "/k","title OPENCODE_COMPARE&& cd /d `"$repo`"&& opencode" -PassThru -WindowStyle Normal

Write-Host "Started rxycode pid=$($pRxy.Id) opencode pid=$($pOc.Id)"
Start-Sleep -Seconds 4

$hRxy = Wait-MainWindow $pRxy 20000
$hOc = Wait-MainWindow $pOc 20000
Write-Host "hwnd rxy=$hRxy oc=$hOc"

if ($hRxy -ne [IntPtr]::Zero) {
  [void][Win]::ShowWindow($hRxy, 5)
  [void][Win]::MoveWindow($hRxy, $leftX, $y, $halfW, $h, $true)
}
if ($hOc -ne [IntPtr]::Zero) {
  [void][Win]::ShowWindow($hOc, 5)
  [void][Win]::MoveWindow($hOc, $rightX, $y, $halfW, $h, $true)
}

Start-Sleep -Seconds 5

# Full desktop before Ctrl+P
Capture-Screen (Join-Path $outDir "01-both-before.png") $screen.X $screen.Y $screen.Width $screen.Height

function Send-CtrlP([IntPtr]$hwnd) {
  if ($hwnd -eq [IntPtr]::Zero) { return }
  [void][Win]::SetForegroundWindow($hwnd)
  Start-Sleep -Milliseconds 400
  [System.Windows.Forms.SendKeys]::SendWait("^p")
  Start-Sleep -Milliseconds 800
}

Send-CtrlP $hRxy
Capture-Screen (Join-Path $outDir "02-rxycode-ctrlp.png") $leftX $y $halfW $h

Send-CtrlP $hOc
Capture-Screen (Join-Path $outDir "03-opencode-ctrlp.png") $rightX $y $halfW $h

Capture-Screen (Join-Path $outDir "04-both-after.png") $screen.X $screen.Y $screen.Width $screen.Height

Write-Host "DONE shots in $outDir"
Get-ChildItem $outDir | Format-Table Name, Length, LastWriteTime
