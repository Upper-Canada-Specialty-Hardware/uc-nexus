# Shared config + helpers for the UC Nexus local dev/test runtime.
# Dot-sourced by the other localdev scripts. Windows PowerShell 5.1+ compatible.

$ErrorActionPreference = 'Stop'

# Repo root is the parent of this script's folder (localdev/).
$RepoRoot = Split-Path -Parent $PSScriptRoot
$LocalDev = Join-Path $RepoRoot '.localdev'
$PgRoot   = Join-Path $LocalDev 'pgsql'      # EDB zip extracts to a top-level pgsql/ folder
$PgBin    = Join-Path $PgRoot 'bin'
$PgData   = Join-Path $LocalDev 'pgdata'
$PgLog    = Join-Path $LocalDev 'postgres.log'

# Connection settings. Override the port with $env:UC_PG_PORT before running if 5432 is taken.
if ($env:UC_PG_PORT) { $PgPort = $env:UC_PG_PORT } else { $PgPort = '5432' }
$PgUser     = 'postgres'
$PgPassword = 'postgres'
$PgDbName   = 'uc_nexus'
$DatabaseUrl = "postgresql://${PgUser}:${PgPassword}@localhost:${PgPort}/${PgDbName}"

function Write-Step([string]$msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg)   { Write-Host "    $msg" -ForegroundColor Green }
function Write-Note([string]$msg) { Write-Host "    $msg" -ForegroundColor Yellow }

function Get-PgExe([string]$name) { return (Join-Path $PgBin ("{0}.exe" -f $name)) }

function Test-PgInstalled { return (Test-Path (Get-PgExe 'pg_ctl')) }

function Test-PgRunning {
  if (-not (Test-Path $PgData)) { return $false }
  & (Get-PgExe 'pg_ctl') -D $PgData status *> $null
  return ($LASTEXITCODE -eq 0)
}

function Get-PsExe {
  $pwsh = Get-Command pwsh -ErrorAction SilentlyContinue
  if ($pwsh) { return $pwsh.Source }
  return 'powershell'
}
