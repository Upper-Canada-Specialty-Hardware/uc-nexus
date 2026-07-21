<#
.SYNOPSIS
  Install the UC Nexus relay on a workstation: extract the onedir bundle, register a logon scheduled task.

.DESCRIPTION
  Extracts the ucnexus-relay onedir bundle (ucnexus-relay.zip, downloaded from the GitHub Release) into a
  per-user install dir under a versioned app-<...>/ folder fronted by a stable `current` junction, seeds a
  config.toml, then registers a Scheduled Task that launches the relay AT LOGON as the current user. Running
  as the interactive user is deliberate: the relay authenticates to GP via Windows SSPI as that domain user
  (the one in DYNGRP), and the DPAPI-encrypted shared_secret is bound to that same user (CurrentUser scope).

  Registering the task writes to Task Scheduler, so this must run from an elevated PowerShell (admin once).
  The relay itself runs un-elevated (RunLevel Limited). For a no-admin self-service install (HKCU Run key +
  tray app), use install-relay-user.ps1 instead.

.PARAMETER ZipPath
  Path to the downloaded ucnexus-relay.zip. Defaults to ..\dist\ucnexus-relay.zip (a local build).

.PARAMETER InstallDir
  The per-user data dir (config.toml, logs, versioned app folders). Defaults to %LOCALAPPDATA%\UCNexusRelay.

.PARAMETER TaskName
  Scheduled task name. Defaults to "UC Nexus Relay".

.PARAMETER StartNow
  Also start the task immediately after install. Only do this once config.toml is enrolled.

.EXAMPLE
  .\install-relay.ps1 -ZipPath C:\Users\me\Downloads\ucnexus-relay.zip
#>
[CmdletBinding()]
param(
    [string]$ZipPath = (Join-Path $PSScriptRoot "..\dist\ucnexus-relay.zip"),
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "UCNexusRelay"),
    [string]$TaskName = "UC Nexus Relay",
    [switch]$StartNow
)
$ErrorActionPreference = "Stop"

# admin check - Register-ScheduledTask needs it
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Error "run this from an elevated PowerShell (Run as administrator) - registering the scheduled task requires it."
    exit 1
}

if (-not (Test-Path $ZipPath)) {
    Write-Error "bundle not found at $ZipPath - download ucnexus-relay.zip from the GitHub Release (or build it with build.ps1) and pass -ZipPath."
    exit 1
}

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

# extract the onedir bundle into a versioned app folder + point the stable `current` junction at it
$appDir = Join-Path $InstallDir "app-installed"
if (Test-Path $appDir) { Remove-Item $appDir -Recurse -Force }
Expand-Archive -Path $ZipPath -DestinationPath $appDir -Force
if (-not (Test-Path (Join-Path $appDir "ucnexus-relay.exe"))) {
    Write-Error "the bundle at $ZipPath did not contain ucnexus-relay.exe"
    exit 1
}
$cur = Join-Path $InstallDir "current"
if (Test-Path $cur) { (Get-Item $cur).Delete() }
New-Item -ItemType Junction -Path $cur -Target $appDir | Out-Null
$curExe = Join-Path $cur "ucnexus-relay.exe"
Write-Host "installed onedir bundle -> $appDir  (current -> $appDir)"

# seed config.toml from the example if the workstation doesn't have one yet (never overwrite a real one -
# it may hold the enrolled DPAPI secret)
$destCfg = Join-Path $InstallDir "config.toml"
if (-not (Test-Path $destCfg)) {
    $exampleCfg = Join-Path $PSScriptRoot "..\config.example.toml"
    if (Test-Path $exampleCfg) {
        Copy-Item -Path $exampleCfg -Destination $destCfg -Force
        Write-Host "seeded config.toml from config.example.toml -> $destCfg (EDIT it: [sql], [gp], [cors], then enroll)"
    } else {
        Write-Warning "no config.example.toml beside the script; create $destCfg by hand before starting the relay."
    }
} else {
    Write-Host "kept existing config.toml at $destCfg"
}

# logon trigger + restart-on-failure, running as the current interactive user, un-elevated, via the stable
# `current` junction path (so a version update - which only repoints the junction - needs no task change)
$user = "$env:USERDOMAIN\$env:USERNAME"
$action = New-ScheduledTaskAction -Execute $curExe -Argument "serve" -WorkingDirectory $InstallDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -DontStopOnIdleEnd

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null
Write-Host "registered scheduled task '$TaskName' (at logon, user $user, restart-on-failure)."

if ($StartNow) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "started '$TaskName' now."
}

Write-Host ""
Write-Host "next steps:"
Write-Host "  1. edit $destCfg  ([sql] server/driver, [gp] companies, [cors] origins)"
Write-Host "  2. enroll (writes the DPAPI-encrypted secret):"
Write-Host "       cd `"$InstallDir`"; & `"$curExe`" enroll --token <TOKEN> --backend-url https://<backend>/graphql"
Write-Host "     (or set [auth] shared_secret by hand, then: & `"$curExe`" protect-secret)"
Write-Host "  3. start it:  Start-ScheduledTask -TaskName `"$TaskName`"   (or just log off and back on)"
Write-Host "  4. verify:    & `"$curExe`" health"
