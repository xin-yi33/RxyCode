param(
    [switch]$KillExisting,
    [string]$Root = "D:\agent-demo\RxyCode\RxyCode1_1_0",
    [string]$Python = "D:\Anaconda3\python.exe"
)

$Labels = @("p6", "p7", "a7")

if ($KillExisting) {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'evals\.cli run' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -match 'cmd|powershell' -and
            $_.CommandLine -match 'monitor-evals|watch-evals|run-evals-baseline|run-p7-baseline|register-p6|a7-evals-manual'
        } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
    Write-Host "KillExisting: eval processes cleared."
}

$procs = @{}
foreach ($label in $Labels) {
    $pidFile = Join-Path $Root "artifacts\gate-$label.pid"
    $oldPid = if (Test-Path $pidFile) { (Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1) } else { $null }
    if ($oldPid -and (Get-Process -Id ([int]$oldPid) -ErrorAction SilentlyContinue)) {
        Write-Host "[$label] already running pid=$oldPid - skipping start."
        $procs[$label] = Get-Process -Id ([int]$oldPid)
        continue
    }
    $outLog = Join-Path $Root "artifacts\gate-$label.log"
    $errLog = Join-Path $Root "artifacts\gate-$label.err.log"
    Remove-Item $outLog, $errLog -ErrorAction SilentlyContinue
    $p = Start-Process -FilePath $Python `
        -ArgumentList '-u','-m','evals.cli','run','--backend','agent','--model','deepseek/deepseek-v4-flash','--tag',"gate-$label",'--compare-baseline','evals\baselines\latest-agent.json' `
        -WorkingDirectory $Root -RedirectStandardOutput $outLog -RedirectStandardError $errLog `
        -WindowStyle Hidden -PassThru
    if ($null -eq $p) {
        Write-Host "[$label] FAILED TO START (Start-Process returned nothing)."
        continue
    }
    $procs[$label] = $p
    Set-Content -Path $pidFile -Value $p.Id -Encoding ASCII
    Write-Host "[$label] started pid=$($p.Id) log=artifacts\gate-$label.log"
}

Write-Host ""
Write-Host "Monitoring 3 gate runs (60s poll). Ctrl+C to stop watching (runs continue)."

while (@($procs.Values | Where-Object { -not $_.HasExited }).Count -gt 0) {
    Start-Sleep -Seconds 60
    foreach ($label in $Labels) {
        $p = $procs[$label]
        $taskLine = ""
        foreach ($log in @((Join-Path $Root "artifacts\gate-$label.err.log"), (Join-Path $Root "artifacts\gate-$label.log"))) {
            if (Test-Path $log) {
                $hit = Select-String -Path $log -Pattern '^\[[0-9]+/17\]' -ErrorAction SilentlyContinue | Select-Object -Last 1
                if ($hit) { $taskLine = $hit.Line; break }
            }
        }
        $done = Select-String -Path (Join-Path $Root "artifacts\gate-$label.log") -Pattern 'Eval suite complete' -ErrorAction SilentlyContinue
        $size = if (Test-Path (Join-Path $Root "artifacts\gate-$label.log")) { (Get-Item (Join-Path $Root "artifacts\gate-$label.log")).Length } else { 0 }
        Write-Host ("[{0}] alive={1} {2} bytes={3}{4}" -f `
            $label, (-not $p.HasExited), ($taskLine -replace '\s+', ' '), $size, $(if ($done) { " DONE" } else { "" }))
    }
}

Write-Host ""
foreach ($label in $Labels) {
    $gateLine = Select-String -Path (Join-Path $Root "artifacts\gate-$label.log") -Pattern '^GATE: (PASS|FAIL)' -ErrorAction SilentlyContinue |
        Select-Object -Last 1
    if ($gateLine) {
        $verdict = if ($gateLine.Line -match 'PASS') { "PASS" } else { "REGRESSION" }
    } else {
        $verdict = "UNKNOWN (no GATE line in log)"
    }
    Write-Host "=== GATE $label : $verdict ==="
    Select-String -Path (Join-Path $Root "artifacts\gate-$label.log") -Pattern 'GATE:|Delta:|Pass Rate' -ErrorAction SilentlyContinue |
        ForEach-Object { Write-Host "   $($_.Line.Trim())" }
}
Write-Host ""
Write-Host "Evidence: artifacts\gate-{p6,p7,a7}.log + evals\results\gate-{p6,p7,a7}.json"
