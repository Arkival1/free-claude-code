<#
.SYNOPSIS
    Shared setup for FCC Studio's Windows scripts. Dot-source it; it does
    nothing on its own.

    Callers set $DryRun (a switch) before dot-sourcing when they support it.
#>

Set-StrictMode -Version Latest

# Windows on ARM emulates x64, whose Python package ecosystem has broader wheel support.
$PythonRequest = "cpython-3.14.0-windows-x86_64-none"
$MinUvVersion = [version] "0.12.13"
$UvInstallUrl = "https://astral.sh/uv/install.ps1"
$DefaultPort = 8082
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not (Test-Path variable:DryRun)) {
    $DryRun = $false
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

function Get-StudioExtras {
    param([switch] $NoVoice, [switch] $WithTraining)
    $extras = @()
    if (-not $NoVoice) {
        $extras += @("--extra", "studio_voice")
    }
    if ($WithTraining) {
        $extras += @("--extra", "lora")
    }
    return , $extras
}

function Install-StudioPackages {
    param([string[]] $Extras, [string] $Note = "first run takes a few minutes")
    $syncArgs = @("sync", "--python", $PythonRequest) + $Extras
    Invoke-Step "Installing Python 3.14 and the app's packages ($Note)" {
        & uv @syncArgs
        if ($LASTEXITCODE -ne 0) { throw "Package install failed (uv exit $LASTEXITCODE)." }
    } "uv $($syncArgs -join ' ')"
}

function Get-ServerArgs {
    param([string[]] $Extras)
    return , (@("run", "--python", $PythonRequest) + $Extras + @("fcc-server"))
}
