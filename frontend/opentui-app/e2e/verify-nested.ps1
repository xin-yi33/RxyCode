# Live verify nested dialogs in a REAL cmd.exe window (not node-pty).
# Handles Chinese IME: after typing, first Enter commits IME, second Enter confirms.
$ErrorActionPreference = "Stop"
$outDir = "d:\agent-demo\RxyCode\RxyCode1_1_0\frontend\opentui-app\e2e\compare-shots"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$repo = "d:\agent-demo\RxyCode\RxyCode1_1_0"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public class WinV2 {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr hWnd, int X, int Y, int W, int H, bool repaint);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
  public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("imm32.dll")] public static extern IntPtr ImmGetContext(IntPtr hWnd);
  [DllImport("imm32.dll")] public static extern bool ImmSetOpenStatus(IntPtr hIMC, bool fOpen);
  [DllImport("imm32.dll")] public static extern bool ImmReleaseContext(IntPtr hWnd, IntPtr hIMC);
  [DllImport("user32.dll")] public static extern IntPtr GetKeyboardLayout(uint idThread);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);
  public const uint WM_INPUTLANGCHANGEREQUEST = 0x0050;
}
"@

function Find-ByTitle([string]$pattern) {
  $found = New-Object System.Collections.Generic.List[object]
  $cb = [WinV2+EnumWindowsProc]{
    param($h,$l)
    if (-not [WinV2]::IsWindowVisible($h)) { return $true }
    $sb = New-Object System.Text.StringBuilder 512
    [void][WinV2]::GetWindowText($h, $sb, $sb.Capacity)
    $t = $sb.ToString()
    if ($t -match $pattern) {
      [uint32]$wpid = 0
      [void][WinV2]::GetWindowThreadProcessId($h, [ref]$wpid)
      $found.Add([pscustomobject]@{ Hwnd=$h; Title=$t; Pid=$wpid })
    }
    return $true
  }
  [void][WinV2]::EnumWindows($cb, [IntPtr]::Zero)
  return $found
}

function Capture([string]$path, [IntPtr]$hwnd) {
  if ($hwnd -eq [IntPtr]::Zero) { return }
  [void][WinV2]::SetForegroundWindow($hwnd)
  Start-Sleep -Milliseconds 250
  $screen = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
  $bmp = New-Object System.Drawing.Bitmap ([int]($screen.Width/2)), $screen.Height
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.CopyFromScreen($screen.X, $screen.Y, 0, 0, $bmp.Size)
  $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
  $g.Dispose(); $bmp.Dispose()
  Write-Host "SHOT $path"
}

function Disable-Ime([IntPtr]$hwnd) {
  try {
    $himc = [WinV2]::ImmGetContext($hwnd)
    if ($himc -ne [IntPtr]::Zero) {
      [void][WinV2]::ImmSetOpenStatus($himc, $false)
      [void][WinV2]::ImmReleaseContext($hwnd, $himc)
    }
  } catch {
    # ignore
  }
}

# Kill old verify windows
Get-Process cmd,rxycode,bun -ErrorAction SilentlyContinue | Where-Object {
  try { $_.MainWindowTitle -match 'RXYCODE_VERIFY' } catch { $false }
} | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 400

$p = Start-Process -FilePath "cmd.exe" -ArgumentList "/k","chcp 65001>nul&& set RXYCODE_TUI=opentui&& set FORCE_COLOR=1&& title RXYCODE_VERIFY&& cd /d `"$repo`"&& rxycode" -PassThru
Write-Host "started pid=$($p.Id)"
Start-Sleep -Seconds 7

$wins = Find-ByTitle "RXYCODE_VERIFY|RxyCode"
$win = $wins | Select-Object -First 1
if (-not $win) { throw "rxycode window not found: $($wins | Out-String)" }
$hwnd = $win.Hwnd
$screen = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
[void][WinV2]::ShowWindow($hwnd, 5)
[void][WinV2]::MoveWindow($hwnd, $screen.X, $screen.Y, [int]($screen.Width/2), $screen.Height, $true)
Start-Sleep -Seconds 2
Disable-Ime $hwnd

function Focus-Send([string]$keys, [int]$waitMs = 700) {
  [void][WinV2]::SetForegroundWindow($hwnd)
  Start-Sleep -Milliseconds 200
  Disable-Ime $hwnd
  [System.Windows.Forms.SendKeys]::SendWait($keys)
  Start-Sleep -Milliseconds $waitMs
}

function Open-Nested([string]$query, [string]$filterShot, [string]$dialogShot) {
  Focus-Send "^p" 900
  Disable-Ime $hwnd
  # Type letter-by-letter to reduce IME buffering
  foreach ($ch in $query.ToCharArray()) {
    Focus-Send $ch 180
  }
  Start-Sleep -Milliseconds 500
  # IME may still be open: first Enter commits composition
  Focus-Send "{ENTER}" 700
  Capture (Join-Path $outDir $filterShot) $hwnd
  # Second Enter confirms the selected command → nested dialog
  Focus-Send "{ENTER}" 1400
  Capture (Join-Path $outDir $dialogShot) $hwnd
  Focus-Send "{ESC}" 500
}

# Palette only
Focus-Send "^p" 1000
Capture (Join-Path $outDir "10-palette.png") $hwnd
Focus-Send "{ESC}" 400

Open-Nested "model" "11-palette-filter-model.png" "12-dialog-model.png"
Open-Nested "session" "13-palette-filter-session.png" "14-dialog-session.png"
Open-Nested "addmodel" "15-palette-filter-addmodel.png" "16-dialog-addmodel.png"

Write-Host "DONE"
Get-ChildItem $outDir\1[0-6]* | Format-Table Name, Length, LastWriteTime

# Leave window open for manual inspection; comment next line to keep it
# Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
