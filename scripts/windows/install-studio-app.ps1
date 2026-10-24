<#
.SYNOPSIS
    Install FCC Studio as a desktop app on this PC.

.DESCRIPTION
    Sets up everything once (uv, Python 3.14, the app's packages, and the
    main AI's voice), then adds an "FCC Studio" icon to your Desktop and
    Start menu. Double-click the icon to open Studio in its own window; the
    server starts and stops with it.

.EXAMPLE
    .\scripts\windows\install-studio-app.ps1
.EXAMPLE
    .\scripts\windows\install-studio-app.ps1 -StartWithWindows
    Also opens FCC Studio when you sign in to Windows.
.EXAMPLE
    .\scripts\windows\install-studio-app.ps1 -Uninstall
    Removes the icons. Your agents, chats, and memory stay in .fcc\studio.
#>
param(
    [switch] $StartWithWindows,
    [switch] $WithTraining,
    [switch] $NoVoice,
    [switch] $NoLaunch,
    [switch] $Uninstall,
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

$AppName = "FCC Studio"
$Launcher = Join-Path $PSScriptRoot "studio-app.ps1"
$Icon = Join-Path $PSScriptRoot "studio.ico"
$PowerShellExe = if ($env:SystemRoot) {
    Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
}
else {
    "powershell.exe"
}

function Get-ShortcutFolders {
    $folders = @()
    if ($DryRun -and -not $env:APPDATA) {
        return @("<Desktop>", "<Start menu>") + $(if ($StartWithWindows) { @("<Startup>") } else { @() })
    }
    $folders += [Environment]::GetFolderPath("Desktop")
    $folders += Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
    if ($StartWithWindows) {
        $folders += Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
    }
    return $folders
}

function New-StudioShortcut {
    param([string] $Folder)
    $path = Join-Path $Folder "$AppName.lnk"
    $launchArgs = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Launcher`""
    if ($NoVoice) { $launchArgs += " -NoVoice" }
    Invoke-Step "Adding the $AppName icon to $Folder" {
        $shell = New-Object -ComObject WScript.Shell
        $link = $shell.CreateShortcut($path)
        $link.TargetPath = $PowerShellExe
        $link.Arguments = $launchArgs
        $link.WorkingDirectory = $RepoRoot
        $link.IconLocation = "$Icon,0"
        $link.WindowStyle = 7
        $link.Description = "Jarvis and your AI team, on this PC"
        $link.Save()
    } "shortcut $path -> $PowerShellExe $launchArgs (icon $Icon)"
}

if ($env:OS -ne "Windows_NT" -and -not $DryRun) {
    throw "The FCC Studio app installer is for Windows."
}

if ($Uninstall) {
    $StartWithWindows = $true
    foreach ($folder in Get-ShortcutFolders) {
        $path = Join-Path $folder "$AppName.lnk"
        Invoke-Step "Removing $path" {
            if (Test-Path $path) { Remove-Item $path }
        } "remove $path"
    }
    Write-Host ""
    Write-Host "Removed the $AppName icons. Your agents, chats, and memory are untouched." -ForegroundColor Green
    exit 0
}

Set-Location $RepoRoot
Write-Host "$AppName - installing from $RepoRoot"
Confirm-Uv
$Extras = Get-StudioExtras -NoVoice:$NoVoice -WithTraining:$WithTraining
$note = "first run takes a few minutes"
if ($WithTraining) { $note = "with LoRA training libraries: a few GB" }
Install-StudioPackages -Extras $Extras -Note $note

foreach ($folder in Get-ShortcutFolders) {
    New-StudioShortcut -Folder $folder
}

Write-Host ""
Write-Host "Done. Double-click '$AppName' on your Desktop or in the Start menu." -ForegroundColor Green
Write-Host "Studio opens in its own window. Close the window to stop it."
Write-Host "Settings are inside the app: the Settings item in the left menu."

if (-not $NoLaunch) {
    Invoke-Step "Opening $AppName" {
        Start-Process -FilePath $PowerShellExe -ArgumentList @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", "`"$Launcher`""
        )
    } "$PowerShellExe -File $Launcher"
}
