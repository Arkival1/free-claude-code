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
    .\scripts\windows\start-studio.ps1 -NoVoice
    Skips the main AI's built-in voice (Kokoro speech and Whisper listening,
    about 150 MB of packages). The browser's voice is used instead.
.EXAMPLE
    .\scripts\windows\start-studio.ps1 -WithTraining
    Also installs PyTorch, transformers, and PEFT so Studio can train LoRA
    adapters on this PC (an NVIDIA GPU is strongly advised).
#>
param(
    [int] $Port = 0,
    [switch] $WithTraining,
    [switch] $NoVoice,
    [switch] $NoBrowser,
    [switch] $DryRun,
    [switch] $Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

. (Join-Path $PSScriptRoot "studio-common.ps1")

function Show-Help {
    Get-Help -Detailed $PSCommandPath | Out-String | Write-Host
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

$Extras = Get-StudioExtras -NoVoice:$NoVoice -WithTraining:$WithTraining
$SyncNote = "first run takes a few minutes"
if ($WithTraining) {
    $SyncNote = "with LoRA training libraries: the first run downloads a few GB"
}
Install-StudioPackages -Extras $Extras -Note $SyncNote

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

$RunArgs = Get-ServerArgs -Extras $Extras
Invoke-Step "Starting the server" {
    & uv @RunArgs
} "uv $($RunArgs -join ' ')"
