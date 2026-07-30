# Continue compare: dismiss OpenCode update dialog, Ctrl+P both, reshoot
$ErrorActionPreference = "Stop"
$outDir = "d:\agent-demo\RxyCode\RxyCode1_1_0\frontend\opentui-app\e2e\compare-shots"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public class Win2 {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr hWnd, int X, int Y, int W, int H, bool repaint);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
  public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
}
"@

function Find-WindowsByTitle([string]$pattern) {
  $found = New-Object System.Collections.Generic.List[object]
  $cb = [Win2+EnumWindowsProc]{
    param($h,$l)
    if (-not [Win2]::IsWindowVisible($h)) { return $true }
    $sb = New-Object System.Text.StringBuilder 512
    [void][Win2]::GetWindowText($h, $sb, $sb.Capacity)
    $t = $sb.ToString()
    if ($t -match $pattern) {
      [uint32]$wpid = 0
      [void][Win2]::GetWindowThreadProcessId($h, [ref]$wpid)
      $found.Add([pscustomobject]@{ Hwnd=$h; Title=$t; Pid=$wpid })
    }
    return $true
  }
  [void][Win2]::EnumWindows($cb, [IntPtr]::Zero)
  return $found
}

function Capture-Screen([string]$path, [int]$x, [int]$y, [int]$w, [int]$h) {
  $bmp = New-Object System.Drawing.Bitmap $w, $h
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.CopyFromScreen($x, $y, 0, 0, (New-Object System.Drawing.Size($w, $h)))
  $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
  $g.Dispose(); $bmp.Dispose()
  Write-Host "SHOT $path"
}

$screen = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
$halfW = [Math]::Floor($screen.Width / 2)
$h = $screen.Height
$leftX = $screen.X
$rightX = $screen.X + $halfW
$y = $screen.Y

$wins = Find-WindowsByTitle "COMPARE|OpenCode|RxyCode|opencode|rxycode|OPENCODE|RXYCODE"
$wins | Format-Table Pid, Title, Hwnd
$rxy = $wins | Where-Object { $_.Title -match 'RXYCODE|RxyCode' } | Select-Object -First 1
$oc = $wins | Where-Object { $_.Title -match 'OPENCODE|OpenCode|opencode' -and $_.Title -notmatch 'Rxy' } | Select-Object -First 1
# fallback: any remaining COMPARE
if (-not $oc) { $oc = $wins | Where-Object { $_.Title -match 'OPENCODE_COMPARE|OPEN' } | Select-Object -First 1 }

Write-Host "rxy=$($rxy.Title) oc=$($oc.Title)"

if ($rxy) {
  [void][Win2]::ShowWindow($rxy.Hwnd, 5)
  [void][Win2]::MoveWindow($rxy.Hwnd, $leftX, $y, $halfW, $h, $true)
}
if ($oc) {
  [void][Win2]::ShowWindow($oc.Hwnd, 5)
  [void][Win2]::MoveWindow($oc.Hwnd, $rightX, $y, $halfW, $h, $true)
}

# Dismiss OpenCode update: Esc then ensure palette
if ($oc) {
  [void][Win2]::SetForegroundWindow($oc.Hwnd)
  Start-Sleep -Milliseconds 500
  [System.Windows.Forms.SendKeys]::SendWait("{ESC}")
  Start-Sleep -Milliseconds 600
  [System.Windows.Forms.SendKeys]::SendWait("{ESC}")
  Start-Sleep -Milliseconds 400
  [System.Windows.Forms.SendKeys]::SendWait("^p")
  Start-Sleep -Milliseconds 1000
  Capture-Screen (Join-Path $outDir "05-opencode-ctrlp-clean.png") $rightX $y $halfW $h
}

if ($rxy) {
  [void][Win2]::SetForegroundWindow($rxy.Hwnd)
  Start-Sleep -Milliseconds 500
  [System.Windows.Forms.SendKeys]::SendWait("{ESC}")
  Start-Sleep -Milliseconds 300
  [System.Windows.Forms.SendKeys]::SendWait("^p")
  Start-Sleep -Milliseconds 1000
  Capture-Screen (Join-Path $outDir "06-rxycode-ctrlp-clean.png") $leftX $y $halfW $h
}

Capture-Screen (Join-Path $outDir "07-both-final.png") $screen.X $screen.Y $screen.Width $screen.Height
Write-Host "DONE"
Get-ChildItem $outDir\0[5-7]* | Format-Table Name, Length
