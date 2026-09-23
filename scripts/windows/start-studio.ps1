<#
.SYNOPSIS
    Start FCC Studio from this folder on Windows.

.DESCRIPTION
    Installs uv if it is missing (uv also installs Python 3.14 for you),
    installs the app's packages into this folder, starts the server, and opens
    Studio in your browser. Press Ctrl+C in this window to stop the server.

.EXAMPLE
    .\scripts\windows\start-studio.ps1
.EXAMPLE
    .\scripts\windows\start-studio.ps1 -Port 9000 -NoBrowser
.EXAMPLE
    .\scripts\windows\start-studio.ps1 -WithTraining
    Also installs PyTorch, transformers, and PEFT so Studio can train LoRA
    adapters on this PC (an NVIDIA GPU is strongly advised).
#>
param(
    [int] $Port = 0,
    [switch] $WithTraining,
    [switch] $NoBrowser,
    [switch] $DryRun,
    [switch] $Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# Windows on ARM emulates x64, whose Python package ecosystem has broader wheel support.
$PythonRequest = "cpython-3.14.0-windows-x86_64-none"
$MinUvVersion = [version] "0.12.13"
$UvInstallUrl = "https://astral.sh/uv/install.ps1"
$DefaultPort = 8082
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

function Show-Help {
    Get-Help -Detailed $PSCommandPath | Out-String | Write-Host
}

function Invoke-Step {
    param([string] $Description, [scriptblock] $Action, [string] $Display)
    Write-Host ""
    Write-Host "==> $Description" -ForegroundColor Cyan
    if ($DryRun) {
        Write-Host "+ $Display"
        return
    }
    & $Action
}

function Get-UvVersion {
    $command = Get-Command uv -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        return $null
    }
    $output = (& $command.Source --version) 2>$null
    if ($output -match "uv (\d+\.\d+\.\d+)") {
        return [version] $Matches[1]
    }
    return $null
}

function Add-UvToPath {
    if (-not $env:USERPROFILE) {
        return
    }
    foreach ($candidate in @(
            (Join-Path $env:USERPROFILE ".local\bin"),
            (Join-Path $env:USERPROFILE ".cargo\bin")
        )) {
        if ((Test-Path $candidate) -and -not ($env:Path -split ";" -contains $candidate)) {
            $env:Path = "$candidate;$env:Path"
        }
    }
}

function Confirm-Uv {
    Add-UvToPath
    $version = Get-UvVersion
    if ($null -eq $version) {
        Invoke-Step "Installing uv (it manages Python for this app)" {
            powershell -NoProfile -ExecutionPolicy Bypass -Command "irm $UvInstallUrl | iex"
            Add-UvToPath
        } "irm $UvInstallUrl | iex"
        if (-not $DryRun -and $null -eq (Get-UvVersion)) {
            throw "uv did not install. Open a new PowerShell window and run this script again."
        }
        return
    }
    if ($version -lt $MinUvVersion) {
        Invoke-Step "Updating uv $version to $MinUvVersion or newer" {
            uv self update
        } "uv self update"
    }
    else {
        Write-Host "uv $version found."
    }
}

function Wait-AndOpenStudio {
    param([int] $TargetPort)
    $healthUrl = "http://127.0.0.1:$TargetPort/health"
    $studioUrl = "http://localhost:$TargetPort/studio"
    Start-Job -ArgumentList $healthUrl, $studioUrl -ScriptBlock {
        param($HealthUrl, $StudioUrl)
        for ($attempt = 0; $attempt -lt 120; $attempt++) {
            try {
                Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 $HealthUrl | Out-Null
                Start-Process $StudioUrl
                return
            }
            catch {
                Start-Sleep -Seconds 1
            }
        }
    } | Out-Null
}

if ($Help) {
    Show-Help
    exit 0
}

if ($env:OS -ne "Windows_NT" -and -not $DryRun) {
    throw "This launcher is for Windows. On macOS or Linux run: uv run fcc-server"
}

Set-Location $RepoRoot
Write-Host "FCC Studio - starting from $RepoRoot"

Confirm-Uv

$SyncArgs = @("sync", "--python", $PythonRequest)
$SyncNote = "first run takes a few minutes"
if ($WithTraining) {
    $SyncArgs += @("--extra", "lora")
    $SyncNote = "with LoRA training libraries: the first run downloads a few GB"
}
Invoke-Step "Installing Python 3.14 and the app's packages ($SyncNote)" {
    & uv @SyncArgs
    if ($LASTEXITCODE -ne 0) { throw "Package install failed (uv exit $LASTEXITCODE)." }
} "uv $($SyncArgs -join ' ')"

$effectivePort = if ($Port -gt 0) { $Port } else { $DefaultPort }
if ($Port -gt 0) {
    $env:PORT = "$Port"
}

if (-not $NoBrowser) {
    if ($DryRun) {
        Write-Host "+ open http://localhost:$effectivePort/studio once the server answers"
    }
    else {
        Wait-AndOpenStudio -TargetPort $effectivePort
    }
}

Write-Host ""
Write-Host "Studio:  http://localhost:$effectivePort/studio" -ForegroundColor Green
Write-Host "Admin:   http://localhost:$effectivePort/admin  (settings, this PC only)"
Write-Host "Phone:   open Studio > More > Install on your iPhone for the address to use."
Write-Host "If Windows Firewall asks, allow Python on Private networks so your phone can connect."
Write-Host "Press Ctrl+C to stop."

$RunArgs = @("run", "--python", $PythonRequest)
if ($WithTraining) {
    $RunArgs += @("--extra", "lora")
}
$RunArgs += "fcc-server"
Invoke-Step "Starting the server" {
    & uv @RunArgs
} "uv $($RunArgs -join ' ')"
