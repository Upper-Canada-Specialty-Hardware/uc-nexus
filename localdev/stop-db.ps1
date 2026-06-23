# Stop the local Postgres server (leaves the cluster + data intact).
. (Join-Path $PSScriptRoot '_common.ps1')

if (-not (Test-PgInstalled)) { Write-Note "Postgres binaries not present; nothing to stop."; return }

if (Test-PgRunning) {
  Write-Step "stopping Postgres"
  & (Get-PgExe 'pg_ctl') -D $PgData -m fast stop | Out-Null
  Write-Ok "stopped"
} else {
  Write-Ok "server not running"
}
