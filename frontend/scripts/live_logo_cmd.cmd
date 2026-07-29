@echo off
REM Live CMD dump of adaptive wordmark (ASCII path)
chcp 65001 >nul
set OUT=%~dp0..\..\qa-artifacts\logo-profiles
if not exist "%OUT%" mkdir "%OUT%"
cd /d "%~dp0.."
set RXYCODE_LOGO_PROFILE=legacy
echo HOST=cmd.exe > "%OUT%\live-cmd-legacy.txt"
echo ARCH=%PROCESSOR_ARCHITECTURE% >> "%OUT%\live-cmd-legacy.txt"
npx --yes tsx scripts/render_logo_profiles.ts "%OUT%" >> "%OUT%\live-cmd-legacy.txt" 2>&1
type "%OUT%\wordmark-legacy-win.txt" >> "%OUT%\live-cmd-legacy.txt"
echo wrote %OUT%\live-cmd-legacy.txt
