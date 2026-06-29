<#
.SYNOPSIS
  Install the UC Nexus relay on a workstation: stage the exe + config, register a logon scheduled task.

.DESCRIPTION
  Copies ucnexus-relay.exe (downloaded from the GitHub Release) and a config.toml into a per-user install
  dir, then registers a Scheduled Task that launches the relay AT LOGON as the current user. Running as the
  interactive user is deliberate: the relay authenticates to GP via Windows SSPI as that domain user (the
  one in DYNGRP), and the DPAPI-encrypted shared_secret is bound to that same user (CurrentUser scope).

  Registering the task writes to Task Scheduler, so this must run from an elevated PowerShell (admin once).
  The relay itself runs un-elevated (RunLevel Limited).

.PARAMETER ExePath
  Path to the downloaded ucnexus-relay.exe. Defaults to ..\dist\ucnexus-relay.exe (a local build).

.PARAMETER InstallDir
  Where to stage the exe + config.toml. Defaults to %LOCALAPPDATA%\UCNexusRelay.

.PARAMETER TaskName
  Scheduled task name. Defaults to "UC Nexus Relay".

.PARAMETER StartNow
  Also start the task immediately after install. Only do this once config.toml is enrolled.

.EXAMPLE
  .\install-relay.ps1 -ExePath C:\Users\me\Downloads\ucnexus-relay.exe
#>
[CmdletBinding()]
param(
    [string]$ExePath = (Join-Path $PSScriptRoot "..\dist\ucnexus-relay.exe"),
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

if (-not (Test-Path $ExePath)) {
    Write-Error "exe not found at $ExePath - download ucnexus-relay.exe from the GitHub Release (or build it with build.ps1) and pass -ExePath."
    exit 1
}

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$destExe = Join-Path $InstallDir "ucnexus-relay.exe"
Copy-Item -Path $ExePath -Destination $destExe -Force
Write-Host "staged exe -> $destExe"

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

# logon trigger + restart-on-failure, running as the current interactive user, un-elevated
$user = "$env:USERDOMAIN\$env:USERNAME"
$action = New-ScheduledTaskAction -Execute $destExe -Argument "serve" -WorkingDirectory $InstallDir
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
Write-Host "       cd `"$InstallDir`"; .\ucnexus-relay.exe enroll --token <TOKEN> --backend-url https://<backend>/graphql"
Write-Host "     (or set [auth] shared_secret by hand, then: .\ucnexus-relay.exe protect-secret)"
Write-Host "  3. start it:  Start-ScheduledTask -TaskName `"$TaskName`"   (or just log off and back on)"
Write-Host "  4. verify:    .\ucnexus-relay.exe health"
