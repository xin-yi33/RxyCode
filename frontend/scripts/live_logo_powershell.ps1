# Live PowerShell 64/32 wordmark dumps
$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not $root) { $root = 'd:\agent-demo\RxyCode\RxyCode1_1_0' }
# Prefer repo-relative from this script: frontend/scripts -> repo
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$out = Join-Path $repo 'qa-artifacts\logo-profiles'
New-Item -ItemType Directory -Force -Path $out | Out-Null
$frontend = Join-Path $repo 'frontend'

function Dump-Profile([string]$label, [string]$profile) {
  $env:RXYCODE_LOGO_PROFILE = $profile
  Push-Location $frontend
  try {
    $body = npx --yes tsx -e @"
import { renderWordmarkFrame } from './src/logo.ts';
import { detectArch, detectLogoProfile } from './src/terminalHost.ts';
console.log('label=$label');
console.log('profile=' + detectLogoProfile() + ' arch=' + detectArch());
console.log(renderWordmarkFrame(100).join('\n'));
"@
    $target = Join-Path $out "live-$label.txt"
    Set-Content -Path $target -Value $body -Encoding UTF8
    Write-Host "wrote $target"
  } finally {
    Pop-Location
  }
}

$bit = if ([Environment]::Is64BitProcess) { 'ps64' } else { 'ps32' }
Dump-Profile "$bit-legacy" 'legacy'
Dump-Profile "$bit-modern" 'modern'
Dump-Profile "$bit-macos" 'macos'

# If running as 64-bit, also spawn 32-bit PowerShell
$ps32 = Join-Path $env:WINDIR 'SysWOW64\WindowsPowerShell\v1.0\powershell.exe'
if ([Environment]::Is64BitProcess -and (Test-Path $ps32)) {
  & $ps32 -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath
}
