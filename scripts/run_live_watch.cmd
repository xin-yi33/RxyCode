@echo off
chcp 65001 >nul
title RxyCode Live AgentV2 Monitor
cd /d "%~dp0.."
echo [monitor] cwd=%CD%
echo [monitor] config=%USERPROFILE%\.RxyCode\config.yaml
echo [monitor] OpenCode Go endpoint: https://opencode.ai/zen/go/v1
echo [monitor] model: deepseek-v4-flash
echo.
python scripts\run_appserver_live_test.py
echo.
echo [monitor] finished exit=%ERRORLEVEL%
pause
