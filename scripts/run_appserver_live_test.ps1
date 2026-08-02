# Run live appserver bootstrap test with 5s heartbeat + streamed logs.
# Usage:
#   .\scripts\run_appserver_live_test.ps1
#   $env:RXYCODE_APPSERVER_LIVE_PROMPT = "1"; .\scripts\run_appserver_live_test.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
python scripts/run_appserver_live_test.py
exit $LASTEXITCODE