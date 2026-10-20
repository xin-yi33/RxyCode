# W10-D1: build the production images rxycode-api / rxycode-worker / rxycode-web
# tagged with the current git short SHA plus :latest. Images are built locally
# and never pushed (D-11). Run from anywhere — the script resolves the repo
# root from its own path and uses it as the docker build context.
# NOTE: keep this file ASCII-only. PS 5.1 reads .ps1 without a BOM as ANSI,
# and non-ASCII comments corrupt parsing of the lines that follow them.
#Requires -Version 5.1
param(
    # Reuse the daemon's layer cache by default; pass -NoCache for a clean build.
    [switch]$NoCache
)
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$DockerDir = Join-Path $RepoRoot "infra\docker"

$Sha = (git -C $RepoRoot rev-parse --short HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or -not $Sha) { throw "git rev-parse --short HEAD failed" }
$BuildTime = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
Write-Host "building images for commit $Sha (built_at $BuildTime)"

$CacheArgs = @()
if ($NoCache) { $CacheArgs += "--no-cache" }

function Build-Image {
    param(
        [string]$Name,
        [string]$Dockerfile,
        [string[]]$ExtraArgs = @()
    )
    $args = @(
        "build",
        "-f", (Join-Path $DockerDir $Dockerfile),
        "--build-arg", "RXYCODE_BUILD_COMMIT=$Sha",
        "--build-arg", "RXYCODE_BUILD_TIME=$BuildTime",
        "-t", "rxycode-${Name}:${Sha}",
        "-t", "rxycode-${Name}:latest"
    ) + $CacheArgs + $ExtraArgs + @($RepoRoot)
    Write-Host "docker $($args -join ' ')"
    & docker @args
    if ($LASTEXITCODE -ne 0) { throw "docker build failed for rxycode-${Name} (exit $LASTEXITCODE)" }
}

Build-Image -Name "api"    -Dockerfile "api.Dockerfile"
Build-Image -Name "worker" -Dockerfile "worker.Dockerfile"
Build-Image -Name "web"    -Dockerfile "web.Dockerfile"

Write-Host ""
Write-Host "built:"
docker images "rxycode-api" "rxycode-worker" "rxycode-web" --format "{{.Repository}}:{{.Tag}}  {{.Size}}"
Write-Host "done. smoke: docker run --rm -p 127.0.0.1:8000:8000 -e RXYCODE_WEB_DATABASE_URL=... -e RXYCODE_WEB_SECRET=... rxycode-api:$Sha"
