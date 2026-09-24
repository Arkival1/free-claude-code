<#
.SYNOPSIS
    Open FCC Studio as a desktop app: its own window, no browser tabs, no
    black console window.

.DESCRIPTION
    The FCC Studio shortcut runs this. It starts the Studio server in the
    background (unless one is already running), shows a small "starting"
    window, then opens Studio in an app window of Microsoft Edge (or Chrome)
    with its own profile, so it has its own taskbar icon and remembers the
    microphone permission. When you close the window, the server it started
    stops too. Run install-studio-app.cmd once first to set everything up.

.EXAMPLE
    .\scripts\windows\studio-app.ps1
.EXAMPLE
    .\scripts\windows\studio-app.ps1 -KeepServer
    Leaves the server running after the window closes, so your phone keeps
    working.
#>
param(
    [int] $Port = 0,
    [switch] $KeepServer,
    [switch] $NoVoice,
    [switch] $DryRun,
    [switch] $Help
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
. (Join-Path $PSScriptRoot "studio-common.ps1")

if ($Help) {
    Get-Help -Detailed $PSCommandPath | Out-String | Write-Host
    exit 0
}

$effectivePort = if ($Port -gt 0) { $Port } else { $DefaultPort }
$HealthUrl = "http://127.0.0.1:$effectivePort/health"
$StudioUrl = "http://localhost:$effectivePort/studio"
$DataRoot = if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA "FCC Studio" } else { Join-Path $RepoRoot ".fcc-studio-app" }
$WindowProfile = Join-Path $DataRoot "window"
$LogDir = Join-Path $DataRoot "logs"

function Show-Problem {
    param([string] $Text)
    if ($DryRun) {
        Write-Host "! $Text"
        return
    }
    try {
        Add-Type -AssemblyName PresentationFramework
        [void] [System.Windows.MessageBox]::Show($Text, "FCC Studio")
    }
    catch {
        Write-Host $Text
    }
}

function Test-Server {
    try {
        Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 $HealthUrl | Out-Null
        return $true
    }
    catch {
        return $false
    }
}

function Show-Splash {
    # A small dark window so double-clicking the icon shows something at once.
    try {
        Add-Type -AssemblyName System.Windows.Forms, System.Drawing
        $form = New-Object System.Windows.Forms.Form
        $form.FormBorderStyle = "None"
        $form.StartPosition = "CenterScreen"
        $form.Size = New-Object System.Drawing.Size(420, 150)
        $form.BackColor = [System.Drawing.Color]::FromArgb(2, 7, 13)
        $form.TopMost = $true
        $form.ShowInTaskbar = $true
        $form.Text = "FCC Studio"
        $icon = Join-Path $PSScriptRoot "studio.ico"
        if (Test-Path $icon) { $form.Icon = New-Object System.Drawing.Icon($icon) }
        $title = New-Object System.Windows.Forms.Label
        $title.Text = "FCC STUDIO"
        $title.ForeColor = [System.Drawing.Color]::FromArgb(255, 200, 97)
        $title.Font = New-Object System.Drawing.Font("Consolas", 18, [System.Drawing.FontStyle]::Bold)
        $title.AutoSize = $true
        $title.Location = New-Object System.Drawing.Point(28, 30)
        $note = New-Object System.Windows.Forms.Label
        $note.Text = "Waking Jarvis up..."
        $note.ForeColor = [System.Drawing.Color]::FromArgb(64, 214, 255)
        $note.Font = New-Object System.Drawing.Font("Consolas", 11)
        $note.AutoSize = $true
        $note.Location = New-Object System.Drawing.Point(30, 82)
        $form.Controls.Add($title)
        $form.Controls.Add($note)
        $form.Show()
        [System.Windows.Forms.Application]::DoEvents()
        return $form
    }
    catch {
        return $null
    }
}

function Find-AppBrowser {
    $candidates = @()
    foreach ($root in @(${env:ProgramFiles(x86)}, $env:ProgramFiles, $env:LOCALAPPDATA)) {
        if (-not $root) { continue }
        $candidates += Join-Path $root "Microsoft\Edge\Application\msedge.exe"
        $candidates += Join-Path $root "Google\Chrome\Application\chrome.exe"
    }
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

function Get-WindowProcesses {
    # The app window's browser processes, found by the profile folder only it uses.
    $needle = [regex]::Escape($WindowProfile)
    Get-CimInstance Win32_Process -Filter "Name='msedge.exe' OR Name='chrome.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -match $needle }
}

function Stop-Server {
    param($Process)
    if ($null -eq $Process -or $Process.HasExited) { return }
    # uv starts Python as a child; stop the whole tree.
    & taskkill.exe /PID $Process.Id /T /F | Out-Null
}

if ($env:OS -ne "Windows_NT" -and -not $DryRun) {
    throw "The FCC Studio app is for Windows. Elsewhere run: uv run fcc-server"
}

$Extras = Get-StudioExtras -NoVoice:$NoVoice
$server = $null
$splash = $null

if (Test-Server) {
    Write-Host "Studio is already running."
}
else {
    if (-not $DryRun -and -not (Test-Path (Join-Path $RepoRoot ".venv"))) {
        Show-Problem "FCC Studio is not set up yet. Open the scripts\windows folder and double-click install-studio-app.cmd first."
        exit 1
    }
    Add-UvToPath
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($null -eq $uv -and -not $DryRun) {
        Show-Problem "uv was not found. Run install-studio-app.cmd again to repair the setup."
        exit 1
    }
    $serverArgs = Get-ServerArgs -Extras $Extras
    if ($Port -gt 0) { $env:PORT = "$Port" }
    if ($DryRun) {
        Write-Host "+ start hidden: uv $($serverArgs -join ' ')"
        Write-Host "+ logs: $LogDir"
    }
    else {
        New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
        $splash = Show-Splash
        # -NoNewWindow shares this script's hidden console, so no black window.
        $server = Start-Process -FilePath $uv.Source -ArgumentList $serverArgs `
            -WorkingDirectory $RepoRoot -NoNewWindow -PassThru `
            -RedirectStandardOutput (Join-Path $LogDir "server.log") `
            -RedirectStandardError (Join-Path $LogDir "server-errors.log")
        $ready = $false
        for ($tick = 0; $tick -lt 240; $tick++) {
            if ($splash) { [System.Windows.Forms.Application]::DoEvents() }
            if (Test-Server) { $ready = $true; break }
            if ($server.HasExited) { break }
            Start-Sleep -Milliseconds 500
        }
        if (-not $ready) {
            if ($splash) { $splash.Close() }
            $tail = ""
            $errors = Join-Path $LogDir "server-errors.log"
            if (Test-Path $errors) { $tail = (Get-Content $errors -Tail 12) -join "`n" }
            Stop-Server $server
            Show-Problem "Studio did not start.`n`n$tail`n`nFull log: $LogDir"
            exit 1
        }
    }
}

$browser = Find-AppBrowser
$windowArgs = @(
    "--app=$StudioUrl",
    "--user-data-dir=`"$WindowProfile`"",
    "--window-size=1500,950",
    "--no-first-run",
    "--no-default-browser-check",
    "--autoplay-policy=no-user-gesture-required"
)
if ($DryRun) {
    Write-Host "+ open window: $(if ($browser) { $browser } else { 'msedge.exe' }) $($windowArgs -join ' ')"
    if (-not $KeepServer) { Write-Host "+ stop the server when the window closes" }
    exit 0
}

if ($null -eq $browser) {
    # No Edge or Chrome: use the default browser; the server keeps running.
    if ($splash) { $splash.Close() }
    Start-Process $StudioUrl
    exit 0
}

New-Item -ItemType Directory -Force -Path $WindowProfile | Out-Null
$window = Start-Process -FilePath $browser -ArgumentList $windowArgs -PassThru
if ($splash) {
    Start-Sleep -Milliseconds 1500
    $splash.Close()
}

if ($null -eq $server -or $KeepServer) {
    exit 0
}

# Wait until every window of this app is closed, then stop the server.
$window.WaitForExit()
do {
    Start-Sleep -Seconds 2
} while (@(Get-WindowProcesses).Count -gt 0)
Stop-Server $server
