<#
.SYNOPSIS
  Install the UC Nexus relay for the CURRENT USER with no admin rights.

.DESCRIPTION
  Stages ucnexus-relay.exe + a config.toml into a per-user install dir, then registers a no-admin logon
  autostart via the HKCU Run key (the exe's `install-autostart` subcommand). Nothing here needs elevation
  - use this on a workstation whose user is not a local admin. For an IT/fleet install that prefers a
  Scheduled Task (restart-on-failure, start-when-available), use install-relay.ps1 instead (needs admin).

  The relay runs as the current interactive user on purpose: it authenticates to GP via Windows SSPI as
  that domain user (the one in DYNGRP), and the DPAPI-encrypted shared_secret is bound to that same user.

.PARAMETER ExePath
  Path to ucnexus-relay.exe. Defaults to ..\dist\ucnexus-relay.exe (a local build). For a real install,
  pass the exe downloaded from the GitHub Release.

.PARAMETER InstallDir
  Where to stage the exe + config.toml. Defaults to %LOCALAPPDATA%\UCNexusRelay.

.PARAMETER StartNow
  Also launch the relay immediately after install. Only do this once config.toml is enrolled.

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

# no-admin logon autostart via the HKCU Run key (the exe registers itself, pointing the Run entry at the
# staged exe). Runs as the current user at logon; no Task Scheduler, no elevation.
& $destExe install-autostart
if ($LASTEXITCODE -ne 0) { Write-Error "install-autostart failed (exit $LASTEXITCODE)"; exit 1 }

if ($StartNow) {
    Start-Process -FilePath $destExe -ArgumentList "serve" -WorkingDirectory $InstallDir -WindowStyle Hidden
    Write-Host "launched the relay now."
}

Write-Host ""
Write-Host "next steps:"
Write-Host "  1. edit $destCfg  ([sql] server/driver, [gp] companies, [channel] backend_url)"
Write-Host "  2. enroll (writes the DPAPI-encrypted secret):"
Write-Host "       cd `"$InstallDir`"; .\ucnexus-relay.exe enroll --token <TOKEN> --backend-url https://<backend>/graphql"
Write-Host "  3. start it now (or just log off and back on):"
Write-Host "       Start-Process `"$destExe`" -ArgumentList serve -WorkingDirectory `"$InstallDir`" -WindowStyle Hidden"
Write-Host "  4. verify:    .\ucnexus-relay.exe health"
Write-Host ""
Write-Host "to remove the autostart later:  .\ucnexus-relay.exe uninstall-autostart"
