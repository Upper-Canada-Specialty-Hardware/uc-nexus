<#
.SYNOPSIS
  Install the UC Nexus relay for the CURRENT USER with no admin rights.

.DESCRIPTION
  Extracts the ucnexus-relay onedir bundle (ucnexus-relay.zip) into a per-user install dir under a
  versioned app-<...>/ folder, points a stable `current` directory junction at it, seeds config.toml,
  registers a no-admin logon autostart via the HKCU Run key (the exe's `install-autostart` subcommand,
  which targets the stable `current` path), and creates Desktop + Start-menu shortcuts. Nothing here needs
  elevation - use this on a workstation whose user is not a local admin. For an IT/fleet install that
  prefers a headless Scheduled Task, use install-relay.ps1 instead (needs admin).

  Onedir (not onefile): the C-extension .pyd live as permanent files in the app folder, so a launch loads
  pre-scanned files instead of re-extracting to %TEMP% every time - that per-launch extraction collides
  with Windows Defender on a fresh self-update and crashes the relaunched relay. Updates swap versions by
  repointing the `current` junction, so shortcuts + autostart (which target `current`) never change.

  The relay runs as the current interactive user on purpose: it authenticates to GP via Windows SSPI as
  that domain user (the one in DYNGRP), and the DPAPI-encrypted shared_secret is bound to that same user.

.PARAMETER ZipPath
  Path to ucnexus-relay.zip. Defaults to ..\dist\ucnexus-relay.zip (a local build). For a real install,
  pass the zip downloaded from the GitHub Release.

.PARAMETER InstallDir
  The per-user data dir (holds config.toml, logs, and the versioned app folders). Defaults to
  %LOCALAPPDATA%\UCNexusRelay.

.PARAMETER StartNow
  Also open the relay app immediately after install, so you can run Setup -> Enroll from its window.

.EXAMPLE
  .\install-relay-user.ps1 -ZipPath C:\Users\me\Downloads\ucnexus-relay.zip -StartNow
#>
[CmdletBinding()]
param(
    [string]$ZipPath = (Join-Path $PSScriptRoot "..\dist\ucnexus-relay.zip"),
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "UCNexusRelay"),
    [switch]$StartNow
)
$ErrorActionPreference = "Stop"

if (-not (Test-Path $ZipPath)) {
    Write-Error "bundle not found at $ZipPath - download ucnexus-relay.zip from the GitHub Release (or build it with build.ps1) and pass -ZipPath."
    exit 1
}

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

# Extract the onedir bundle into a versioned app folder. Updates create their own app-<build>/ folders and
# repoint `current`; this initial one is named generically and is cleaned up once an update supersedes it.
$appDir = Join-Path $InstallDir "app-installed"
if (Test-Path $appDir) { Remove-Item $appDir -Recurse -Force }
Expand-Archive -Path $ZipPath -DestinationPath $appDir -Force
$exe = Join-Path $appDir "ucnexus-relay.exe"
if (-not (Test-Path $exe)) {
    Write-Error "the bundle at $ZipPath did not contain ucnexus-relay.exe"
    exit 1
}

# Stable `current` junction -> the active version. Shortcuts + autostart target this, never a versioned path.
$cur = Join-Path $InstallDir "current"
if (Test-Path $cur) { (Get-Item $cur).Delete() }
New-Item -ItemType Junction -Path $cur -Target $appDir | Out-Null
$curExe = Join-Path $cur "ucnexus-relay.exe"
Write-Host "installed onedir bundle -> $appDir  (current -> $appDir)"

# seed config.toml from the example if this workstation doesn't have one yet (never overwrite a real one -
# it may hold the enrolled DPAPI secret)
$destCfg = Join-Path $InstallDir "config.toml"
if (-not (Test-Path $destCfg)) {
    $exampleCfg = Join-Path $PSScriptRoot "..\config.example.toml"
    if (Test-Path $exampleCfg) {
        Copy-Item -Path $exampleCfg -Destination $destCfg -Force
        Write-Host "seeded config.toml from config.example.toml -> $destCfg (EDIT it: [sql], [gp], [channel], then enroll)"
    } else {
        Write-Warning "no config.example.toml beside the script; create $destCfg by hand before starting the relay."
    }
} else {
    Write-Host "kept existing config.toml at $destCfg"
}

# no-admin logon autostart via the HKCU Run key, set directly (the exe is GUI-subsystem, so `& exe
# install-autostart` returns immediately without a usable $LASTEXITCODE). This targets the stable `current`
# path and matches the key/value the relay's own autostart-status / uninstall-autostart use, so the UI
# "start at logon" toggle stays in sync.
$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
New-ItemProperty -Path $runKey -Name "UC Nexus Relay" -Value "`"$curExe`" app --minimized" -PropertyType String -Force | Out-Null
Write-Host "registered HKCU Run autostart -> `"$curExe`" app --minimized"

# Desktop + Start-menu shortcuts that open the app (window + tray), via the stable `current` path.
$wsh = New-Object -ComObject WScript.Shell
$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
foreach ($lnkDir in @([Environment]::GetFolderPath("Desktop"), $startMenu)) {
    $lnk = $wsh.CreateShortcut((Join-Path $lnkDir "UC Nexus Relay.lnk"))
    $lnk.TargetPath = $curExe
    $lnk.Arguments = "app"
    $lnk.WorkingDirectory = $InstallDir
    $lnk.Description = "UC Nexus Relay"
    $lnk.Save()
}
Write-Host "created Desktop + Start-menu shortcuts (UC Nexus Relay)."

if ($StartNow) {
    Start-Process -FilePath $curExe -ArgumentList "app" -WorkingDirectory $InstallDir
    Write-Host "launched the UC Nexus Relay app."
}

Write-Host ""
Write-Host "next steps (all in the relay app window - open it from the Desktop shortcut):"
Write-Host "  1. Setup tab: pick the GP company, then Test GP connection."
Write-Host "  2. In UC Nexus: Admin -> Relay Installs -> Provision install -> copy the one-time token."
Write-Host "  3. Setup tab: paste the token into Enrollment token -> Enroll, then Restart relay (Status tab)."
Write-Host "  The app runs in the system tray and starts at logon; minimizing hides it to the tray, X shuts it down."
