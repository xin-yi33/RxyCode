[CmdletBinding()]
param(
    [Alias("f")]
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$DefaultVersion = "1.2.0"
$Repository = "https://github.com/xin-yi33/RxyCode.git"
$UvInstallerUrl = "https://astral.sh/uv/install.ps1"
$MaxInstallerBytes = 2MB

function Get-ProcessEnvironmentValue {
    param([Parameter(Mandatory = $true)][string]$Name)

    return [Environment]::GetEnvironmentVariable($Name, "Process")
}

function Test-EnabledFlag {
    param([string]$Value)

    return $Value -eq "1"
}

function Get-InstallSource {
    $configuredSource = Get-ProcessEnvironmentValue "RXYCODE_SOURCE"
    if (-not [string]::IsNullOrWhiteSpace($configuredSource)) {
        if ($configuredSource.IndexOfAny([char[]]"`r`n") -ge 0) {
            throw "RXYCODE_SOURCE must not contain line breaks."
        }
        if (Test-Path -LiteralPath $configuredSource) {
            return (Resolve-Path -LiteralPath $configuredSource).Path
        }
        return $configuredSource
    }

    $version = Get-ProcessEnvironmentValue "RXYCODE_VERSION"
    if ([string]::IsNullOrWhiteSpace($version)) {
        $version = $DefaultVersion
    }
    if ($version -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$') {
        throw "RXYCODE_VERSION may contain only letters, digits, '.', '_' and '-'."
    }
    if (-not $version.StartsWith("v", [StringComparison]::OrdinalIgnoreCase)) {
        $version = "v$version"
    }
    return "git+$Repository@$version"
}

function Find-UvExecutable {
    $command = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -ne $command) {
        return $command.Source
    }

    $candidates = [System.Collections.Generic.List[string]]::new()
    $uvInstallDir = Get-ProcessEnvironmentValue "UV_INSTALL_DIR"
    $xdgBinHome = Get-ProcessEnvironmentValue "XDG_BIN_HOME"
    $userProfile = Get-ProcessEnvironmentValue "USERPROFILE"
    if (-not [string]::IsNullOrWhiteSpace($uvInstallDir)) {
        $candidates.Add((Join-Path $uvInstallDir "uv.exe"))
    }
    if (-not [string]::IsNullOrWhiteSpace($xdgBinHome)) {
        $candidates.Add((Join-Path $xdgBinHome "uv.exe"))
    }
    if (-not [string]::IsNullOrWhiteSpace($userProfile)) {
        $candidates.Add((Join-Path $userProfile ".local\bin\uv.exe"))
        $candidates.Add((Join-Path $userProfile ".cargo\bin\uv.exe"))
    }

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return $null
}

function Format-DryRunArgument {
    param([Parameter(Mandatory = $true)][string]$Value)

    if ($Value -match '^[A-Za-z0-9_./:@+,-]+$') {
        return $Value
    }
    return "'" + $Value.Replace("'", "''") + "'"
}

function Invoke-Uv {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "uv failed with exit code $LASTEXITCODE."
    }
}

function Install-Uv {
    param([bool]$NoModifyPath)

    $systemTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    $tempRoot = Join-Path $systemTemp ("rxycode-uv-" + [Guid]::NewGuid().ToString("N"))
    $tempRoot = [IO.Path]::GetFullPath($tempRoot)
    if (-not $tempRoot.StartsWith($systemTemp, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to create a temporary directory outside the system temp directory."
    }

    try {
        New-Item -ItemType Directory -Path $tempRoot -ErrorAction Stop | Out-Null
        $installerPath = Join-Path $tempRoot "uv-install.ps1"
        Write-Host "Downloading the official uv installer from $UvInstallerUrl"
        Invoke-WebRequest -UseBasicParsing -Uri $UvInstallerUrl -OutFile $installerPath

        $installer = Get-Item -LiteralPath $installerPath
        if ($installer.Length -le 0 -or $installer.Length -gt $MaxInstallerBytes) {
            throw "The downloaded uv installer has an unexpected size."
        }
        if (-not (Select-String -LiteralPath $installerPath -SimpleMatch "uv" -Quiet)) {
            throw "The downloaded file does not look like the uv installer."
        }

        $powerShellExecutable = (Get-Process -Id $PID).Path
        $bootstrapArguments = @("-NoLogo", "-NoProfile")
        $isWindowsPlatform = (
            $PSVersionTable.PSEdition -eq "Desktop" -or
            $env:OS -eq "Windows_NT"
        )
        if ($isWindowsPlatform) {
            $bootstrapArguments += @("-ExecutionPolicy", "Bypass")
        }
        $bootstrapArguments += @("-File", $installerPath)

        $previousUvNoModifyPath = Get-ProcessEnvironmentValue "UV_NO_MODIFY_PATH"
        try {
            if ($NoModifyPath) {
                $env:UV_NO_MODIFY_PATH = "1"
            }
            & $powerShellExecutable @bootstrapArguments
            if ($LASTEXITCODE -ne 0) {
                throw "The uv installer failed with exit code $LASTEXITCODE."
            }
        }
        finally {
            if ($null -eq $previousUvNoModifyPath) {
                Remove-Item Env:UV_NO_MODIFY_PATH -ErrorAction SilentlyContinue
            }
            else {
                $env:UV_NO_MODIFY_PATH = $previousUvNoModifyPath
            }
        }
    }
    finally {
        if (Test-Path -LiteralPath $tempRoot) {
            Remove-Item -LiteralPath $tempRoot -Recurse -Force
        }
    }
}

try {
    $source = Get-InstallSource
    $noModifyPath = Test-EnabledFlag (Get-ProcessEnvironmentValue "RXYCODE_NO_MODIFY_PATH")
    $dryRun = Test-EnabledFlag (Get-ProcessEnvironmentValue "RXYCODE_INSTALL_DRY_RUN")
    $uvExecutable = Find-UvExecutable

    $installArguments = [System.Collections.Generic.List[string]]::new()
    $installArguments.Add("tool")
    $installArguments.Add("install")
    # Re-running the bootstrap is an install/upgrade operation. --force keeps
    # it idempotent even when the same tag is already present.
    $installArguments.Add("--force")
    $installArguments.Add($source)

    if ($dryRun) {
        if ([string]::IsNullOrWhiteSpace($uvExecutable)) {
            Write-Host "[dry-run] download $UvInstallerUrl to a temporary file and execute it"
            $uvExecutable = "uv"
        }
        $rendered = @($uvExecutable) + $installArguments |
            ForEach-Object { Format-DryRunArgument ([string]$_) }
        Write-Host ("[dry-run] " + ($rendered -join " "))
        if (-not $noModifyPath) {
            Write-Host ("[dry-run] " + (Format-DryRunArgument $uvExecutable) + " tool update-shell")
        }
        exit 0
    }

    if ([string]::IsNullOrWhiteSpace($uvExecutable)) {
        Install-Uv -NoModifyPath $noModifyPath
        $uvExecutable = Find-UvExecutable
    }
    if ([string]::IsNullOrWhiteSpace($uvExecutable)) {
        throw "uv was installed but could not be found. Add its bin directory to PATH and retry."
    }

    Invoke-Uv -Executable $uvExecutable -Arguments $installArguments.ToArray()
    if (-not $noModifyPath) {
        Invoke-Uv -Executable $uvExecutable -Arguments @("tool", "update-shell")
    }

    Write-Host "RxyCode is installed. Run 'rxycode' from a new terminal."
    if ($noModifyPath) {
        Write-Host "PATH was not modified; add the uv tool bin directory to PATH manually."
    }
}
catch {
    [Console]::Error.WriteLine("RxyCode installation failed: " + $_.Exception.Message)
    exit 1
}
