# Shared config + helpers for the UC Nexus local dev/test runtime.
# Dot-sourced by the other localdev scripts. Windows PowerShell 5.1+ compatible.
#
# Model: one machine-level Postgres server + shared dev secrets, shared by every
# checkout and git worktree on this device. Each worktree gets its own branch-scoped
# database and its own app ports, so multiple worktrees run + test concurrently
# without colliding. See README.md.

$ErrorActionPreference = 'Stop'

# --- Paths -----------------------------------------------------------------
# Repo root is the parent of this script's folder (localdev/). With git worktrees this
# resolves to the *current worktree*, which is what we want for per-branch state.
$RepoRoot = Split-Path -Parent $PSScriptRoot

# Machine-level home, shared by every checkout/worktree. The portable Postgres (binaries
# + the single cluster) and the shared dev secrets live here, so a fresh worktree finds
# them without re-downloading binaries or re-pasting keys. Override with UC_LOCALDEV_HOME.
if ($env:UC_LOCALDEV_HOME) { $UcHome = $env:UC_LOCALDEV_HOME }
else { $UcHome = Join-Path $env:LOCALAPPDATA 'uc-nexus' }

$LocalDev   = Join-Path $UcHome 'localdev'   # postgres binaries + cluster + log + zip
$PgRoot     = Join-Path $LocalDev 'pgsql'    # EDB zip extracts to a top-level pgsql/ folder
$PgBin      = Join-Path $PgRoot 'bin'
$PgData     = Join-Path $LocalDev 'pgdata'
$PgLog      = Join-Path $LocalDev 'postgres.log'
$SecretsEnv = Join-Path $UcHome 'secrets.env'   # shared dev keys, paste once per machine
$PortsFile  = Join-Path $UcHome 'ports.json'    # per-branch app-port reservations

# --- Connection settings ---------------------------------------------------
if ($env:UC_PG_PORT) { $PgPort = $env:UC_PG_PORT } else { $PgPort = '5432' }
$PgUser     = 'postgres'
$PgPassword = 'postgres'

# --- Branch -> isolated database + app ports -------------------------------
function Get-GitBranch {
  try {
    $b = (& git -C $RepoRoot rev-parse --abbrev-ref HEAD 2>$null)
    if ($LASTEXITCODE -eq 0 -and $b) { return $b.Trim() }
  } catch {}
  return 'master'
}

function ConvertTo-Slug([string]$s) {
  $x = $s.ToLowerInvariant() -replace '[^a-z0-9]+', '_'
  $x = $x.Trim('_')
  if ($x.Length -gt 40) { $x = $x.Substring(0, 40).Trim('_') }
  if (-not $x) { $x = 'branch' }
  return $x
}

$Branch   = Get-GitBranch
$IsMaster = ($Branch -eq 'master' -or $Branch -eq 'main')

if ($env:UC_PG_DB) { $PgDbName = $env:UC_PG_DB }
elseif ($IsMaster) { $PgDbName = 'uc_nexus' }
else { $PgDbName = 'uc_nexus_' + (ConvertTo-Slug $Branch) }

$DatabaseUrl = "postgresql://${PgUser}:${PgPassword}@localhost:${PgPort}/${PgDbName}"

# Deterministic per-branch offset (0..97) so a branch tends to land on stable ports even
# before bootstrap reserves them.
function Get-BranchOffset([string]$s) {
  $h = 0
  foreach ($c in $s.ToCharArray()) { $h = (($h * 31) + [int]$c) % 98 }
  return [int]$h
}

function Test-PortFree([int]$port) {
  try {
    $l = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $port)
    $l.Start(); $l.Stop(); return $true
  } catch { return $false }
}

function Read-PortsRegistry {
  if (Test-Path $PortsFile) {
    try { return (Get-Content -Raw $PortsFile | ConvertFrom-Json) } catch { return $null }
  }
  return $null
}

# Resolve this worktree's app ports. master pins 8000/5173. Otherwise prefer the pair
# reserved by bootstrap-worktree (registry), else fall back to the deterministic offset
# so start-* still work without a prior bootstrap.
function Resolve-Ports {
  if ($env:UC_BACKEND_PORT -and $env:UC_FRONTEND_PORT) {
    return @{ Backend = [int]$env:UC_BACKEND_PORT; Frontend = [int]$env:UC_FRONTEND_PORT }
  }
  if ($IsMaster) { return @{ Backend = 8000; Frontend = 5173 } }
  $reg = Read-PortsRegistry
  if ($reg -and ($reg.PSObject.Properties.Name -contains $PgDbName)) {
    return @{ Backend = [int]$reg.$PgDbName.backend; Frontend = [int]$reg.$PgDbName.frontend }
  }
  $off = Get-BranchOffset $Branch
  return @{ Backend = 8000 + $off; Frontend = 5173 + $off }
}

$ports        = Resolve-Ports
$BackendPort  = $ports.Backend
$FrontendPort = $ports.Frontend

# --- Output helpers --------------------------------------------------------
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

# Parse a simple KEY=VALUE env file into a hashtable (ignores blanks + # comments).
function Read-EnvFile([string]$path) {
  $h = @{}
  if (-not (Test-Path $path)) { return $h }
  foreach ($line in Get-Content $path) {
    $t = $line.Trim()
    if (-not $t -or $t.StartsWith('#')) { continue }
    $i = $t.IndexOf('=')
    if ($i -lt 1) { continue }
    $h[$t.Substring(0, $i).Trim()] = $t.Substring($i + 1).Trim()
  }
  return $h
}
