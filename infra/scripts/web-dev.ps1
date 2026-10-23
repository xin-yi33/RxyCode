# W9 local dev: dev Postgres (rxy-web-dev-pg @ 127.0.0.1:55440) + Alembic
# upgrade head + API on http://127.0.0.1:8000 (RXYCODE_WEB_REGISTRATION=open).
# Then run `npm --prefix apps/web run dev` in another terminal (Vite proxies
# /api). There is no worker in dev, so submitted runs stay "queued" — that is
# the expected behavior.
# NOTE: keep this file ASCII-only. PS 5.1 reads .ps1 without a BOM as ANSI,
# and non-ASCII comments corrupt parsing of the lines that follow them.
#Requires -Version 5.1
param(
    # 8000/5173 are the defaults, but the rxydemo stack owns them on this box —
    # pass -ApiPort/-UiPort when they are taken.
    [int]$ApiPort = 8000,
    [int]$UiPort = 5173
)
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Container = "rxy-web-dev-pg"
$PgUrl = "postgresql+psycopg://postgres@127.0.0.1:55440/rxycode"
$SecretFile = Join-Path $env:USERPROFILE ".rxycode\web-dev.secret"

# --- 1. dev Postgres -------------------------------------------------------
# NOTE: probes go through `cmd /c ... 2>nul` — under -ErrorActionPreference
# Stop, PS 5.1 turns ANY native stderr into a terminating NativeCommandError
# even when the stream is merged, and an absent container is an expected
# failure here.
function Test-PgReady {
    cmd /c "docker exec $Container pg_isready -U postgres -d rxycode >nul 2>nul"
    return ($LASTEXITCODE -eq 0)
}

if (-not (Test-PgReady)) {
    cmd /c "docker inspect $Container >nul 2>nul"
    if ($LASTEXITCODE -eq 0) {
        Write-Host "starting existing container $Container"
        docker start $Container | Out-Null
    } else {
        Write-Host "creating container $Container"
        docker run -d --name $Container `
            -e POSTGRES_HOST_AUTH_METHOD=trust `
            -e POSTGRES_DB=rxycode `
            -p 127.0.0.1:55440:5432 postgres:16 | Out-Null
    }
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline -and -not (Test-PgReady)) {
        Start-Sleep -Seconds 1
    }
    if (-not (Test-PgReady)) {
        docker logs $Container 2>&1 | Out-Host
        throw "postgres container $Container did not become ready"
    }
}

# --- 2. PYTHONPATH (same set tests/web conftest uses) ------------------------
$srcDirs = @(
    "rxycode-server",
    "rxycode-worker",
    "rxycode-runner",
    "rxycode-protocol",
    "rxycode-core"
) | ForEach-Object { Join-Path $RepoRoot "packages\$_\src" }
# The repo-root parent lets `RxyCode.RxyCode1_1_0.api_server` resolve as a
# namespace package even without an editable install.
$env:PYTHONPATH = ($srcDirs + (Split-Path $RepoRoot -Parent)) -join ";"

# --- 3. Alembic upgrade head ------------------------------------------------
Write-Host "migrating $PgUrl to alembic head"
python -c "from rxycode_server.persistence.migrate import upgrade_head; upgrade_head('$PgUrl')"
if ($LASTEXITCODE -ne 0) { throw "alembic upgrade head failed" }

# --- 4. web secret (generated once, reused afterwards) ----------------------
if (-not (Test-Path $SecretFile)) {
    New-Item -ItemType Directory -Force -Path (Split-Path $SecretFile) | Out-Null
    $bytes = New-Object byte[] 36
    # .NET Framework (PS 5.1) has no RandomNumberGenerator.Fill — use the CSP.
    $rng = New-Object System.Security.Cryptography.RNGCryptoServiceProvider
    $rng.GetBytes($bytes)
    $rng.Dispose()
    [Convert]::ToBase64String($bytes) | Set-Content -NoNewline -Encoding ascii $SecretFile
}
$Secret = (Get-Content $SecretFile -Raw).Trim()

# --- 5. API on :8000 --------------------------------------------------------
$env:RXYCODE_WEB_REGISTRATION = "open"
$env:RXYCODE_WEB_DATABASE_URL = $PgUrl
$env:RXYCODE_WEB_SECRET = $Secret
$env:RXYCODE_WEB_ORIGINS = "http://127.0.0.1:$UiPort,http://localhost:$UiPort"

$servePy = @'
import os
import uvicorn
from rxycode_server.main import serve

app = serve(
    mode="local",
    host="127.0.0.1",
    database_url=os.environ["RXYCODE_WEB_DATABASE_URL"],
    secret=os.environ["RXYCODE_WEB_SECRET"],
    allowed_origins=[
        origin.strip()
        for origin in os.environ.get("RXYCODE_WEB_ORIGINS", "").split(",")
        if origin.strip()
    ],
)
uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("RXYCODE_WEB_PORT", "8000")))
'@
$servePath = Join-Path $env:TEMP "rxycode_web_dev_serve.py"
Set-Content -Encoding ascii -Path $servePath -Value $servePy

Write-Host "API listening on http://127.0.0.1:$ApiPort (registration=open)"
Write-Host "UI: VITE_API_TARGET=http://127.0.0.1:$ApiPort npm --prefix apps/web run dev  ->  http://127.0.0.1:$UiPort"
$env:RXYCODE_WEB_PORT = "$ApiPort"
python $servePath
