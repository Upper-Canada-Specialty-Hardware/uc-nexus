<#
.SYNOPSIS
  Install the UC Nexus relay for the CURRENT USER with no admin rights.

.DESCRIPTION
  Stages ucnexus-relay.exe + a config.toml into a per-user install dir, registers a no-admin logon
  autostart via the HKCU Run key (the exe's `install-autostart` subcommand, which launches the desktop
  app minimized to the tray), and creates Desktop + Start-menu shortcuts. Nothing here needs elevation -
  use this on a workstation whose user is not a local admin. For an IT/fleet install that prefers a
  headless Scheduled Task, use install-relay.ps1 instead (needs admin).

  The relay runs as the current interactive user on purpose: it authenticates to GP via Windows SSPI as
  that domain user (the one in DYNGRP), and the DPAPI-encrypted shared_secret is bound to that same user.

  The relay runs as the current interactive user on purpose: it authenticates to GP via Windows SSPI as
  that domain user (the one in DYNGRP), and the DPAPI-encrypted shared_secret is bound to that same user.

.PARAMETER ExePath
  Path to ucnexus-relay.exe. Defaults to ..\dist\ucnexus-relay.exe (a local build). For a real install,
  pass the exe downloaded from the GitHub Release.

.PARAMETER InstallDir
  Where to stage the exe + config.toml. Defaults to %LOCALAPPDATA%\UCNexusRelay.

.PARAMETER StartNow
  Also open the relay app immediately after install, so you can run Setup -> Enroll from its window.

.EXAMPLE
  .\install-relay-user.ps1 -ExePath C:\Users\me\Downloads\ucnexus-relay.exe -StartNow
#>
[CmdletBinding()]
param(
    [string]$ExePath = (Join-Path $PSScriptRoot "..\dist\ucnexus-relay.exe"),
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "UCNexusRelay"),
    [switch]$StartNow
)
$ErrorActionPreference = "Stop"

if (-not (Test-Path $ExePath)) {
    Write-Error "exe not found at $ExePath - download ucnexus-relay.exe from the GitHub Release (or build it with build.ps1) and pass -ExePath."
    exit 1
}

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$destExe = Join-Path $InstallDir "ucnexus-relay.exe"
Copy-Item -Path $ExePath -Destination $destExe -Force
Write-Host "staged exe -> $destExe"

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

# no-admin logon autostart via the HKCU Run key (the exe registers itself). The Run entry launches
# `app --minimized` at logon, so the relay comes up in the system tray. No Task Scheduler, no elevation.
& $destExe install-autostart
if ($LASTEXITCODE -ne 0) { Write-Error "install-autostart failed (exit $LASTEXITCODE)"; exit 1 }

# Desktop + Start-menu shortcuts that open the app (window + tray).
$wsh = New-Object -ComObject WScript.Shell
$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
foreach ($lnkDir in @([Environment]::GetFolderPath("Desktop"), $startMenu)) {
    $lnk = $wsh.CreateShortcut((Join-Path $lnkDir "UC Nexus Relay.lnk"))
    $lnk.TargetPath = $destExe
    $lnk.Arguments = "app"
    $lnk.WorkingDirectory = $InstallDir
    $lnk.Description = "UC Nexus Relay"
    $lnk.Save()
}
Write-Host "created Desktop + Start-menu shortcuts (UC Nexus Relay)."

if ($StartNow) {
    Start-Process -FilePath $destExe -ArgumentList "app" -WorkingDirectory $InstallDir
    Write-Host "launched the UC Nexus Relay app."
}

Write-Host ""
Write-Host "next steps (all in the relay app window - open it from the Desktop shortcut):"
Write-Host "  1. Setup tab: pick the GP company, then Test GP connection."
Write-Host "  2. In UC Nexus: Admin -> Relay Installs -> Provision install -> copy the one-time token."
Write-Host "  3. Setup tab: paste the token into Enrollment token -> Enroll, then Restart relay (Status tab)."
Write-Host "  The app runs in the system tray and starts at logon; minimizing hides it to the tray, X shuts it down."
