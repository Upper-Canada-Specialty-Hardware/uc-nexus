# Wipe the local Postgres cluster and rebuild it from scratch (re-init + re-migrate).
# Heavy hammer - for day-to-day data resets, use the in-app "drop and rebuild schema" action.
. (Join-Path $PSScriptRoot '_common.ps1')

Write-Note "This deletes the entire local dev database cluster at $PgData."

if (Test-PgRunning) {
  Write-Step "stopping Postgres"
  & (Get-PgExe 'pg_ctl') -D $PgData -m immediate stop | Out-Null
}

if (Test-Path $PgData) {
  Remove-Item -Recurse -Force $PgData
  Write-Ok "removed $PgData"
}

# Re-init + start + migrate.
& (Join-Path $PSScriptRoot 'start-db.ps1')
