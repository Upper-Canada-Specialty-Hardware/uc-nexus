<#
.SYNOPSIS
  Remove the UC Nexus relay: the logon scheduled task and/or the HKCU Run autostart entry, the `current`
  junction, and optionally the install dir.

.PARAMETER TaskName
  Scheduled task name (admin install). Defaults to "UC Nexus Relay".

.PARAMETER InstallDir
  Install dir. Defaults to %LOCALAPPDATA%\UCNexusRelay.

.PARAMETER RemoveFiles
  Also delete the install dir (versioned app folders + config.toml). The config holds the enrolled DPAPI
  secret, so this is off by default.

.EXAMPLE
  .\uninstall-relay.ps1
  .\uninstall-relay.ps1 -RemoveFiles
#>
[CmdletBinding()]
param(
    [string]$TaskName = "UC Nexus Relay",
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "UCNexusRelay"),
    [switch]$RemoveFiles
)
$ErrorActionPreference = "Stop"

# stop any running relay so its files unlock before we remove them
Get-Process ucnexus-relay -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

# remove the no-admin HKCU Run autostart entry (user install), if present
$run = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
if (Get-ItemProperty -Path $run -Name "UC Nexus Relay" -ErrorAction SilentlyContinue) {
    Remove-ItemProperty -Path $run -Name "UC Nexus Relay" -Force
    Write-Host "removed HKCU Run autostart entry."
}

# remove the scheduled task (admin install), if present - unregistering needs admin
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    $isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()
        ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        Write-Warning "scheduled task '$TaskName' exists but removing it needs an elevated PowerShell; skipped."
    } else {
        try { Stop-ScheduledTask -TaskName $TaskName -ErrorAction Stop } catch {}
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "removed scheduled task '$TaskName'."
    }
}

# remove the `current` junction (just the reparse point) before any file deletion, so a recursive delete
# can't follow it into the target
$cur = Join-Path $InstallDir "current"
if (Test-Path $cur) {
    (Get-Item $cur).Delete()
    Write-Host "removed the current junction."
}

if ($RemoveFiles) {
    if (Test-Path $InstallDir) {
        Remove-Item -Recurse -Force $InstallDir
        Write-Host "deleted $InstallDir."
    }
} else {
    Write-Host "left install dir $InstallDir in place (use -RemoveFiles to delete it)."
}
