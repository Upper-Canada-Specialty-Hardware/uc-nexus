<#
.SYNOPSIS
  Remove the UC Nexus relay scheduled task (and optionally the install dir).

.PARAMETER TaskName
  Scheduled task name. Defaults to "UC Nexus Relay".

.PARAMETER InstallDir
  Install dir to delete when -RemoveFiles is given. Defaults to %LOCALAPPDATA%\UCNexusRelay.

.PARAMETER RemoveFiles
  Also delete the install dir (exe + config.toml). The config holds the enrolled DPAPI secret, so this is
  off by default.

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

$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Error "run this from an elevated PowerShell - unregistering the scheduled task requires it."
    exit 1
}

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    try { Stop-ScheduledTask -TaskName $TaskName -ErrorAction Stop } catch {}
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "removed scheduled task '$TaskName'."
} else {
    Write-Host "no scheduled task '$TaskName' found."
}

if ($RemoveFiles) {
    if (Test-Path $InstallDir) {
        Remove-Item -Recurse -Force $InstallDir
        Write-Host "deleted $InstallDir."
    }
} else {
    Write-Host "left install dir $InstallDir in place (use -RemoveFiles to delete it)."
}
