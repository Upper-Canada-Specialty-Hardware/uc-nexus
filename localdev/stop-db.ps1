# Stop the shared local Postgres server (leaves all cluster data intact).
# NOTE: the server is shared by every worktree on this machine, so stopping it takes the
# database down for ALL of them. To clean up a single branch's data instead, use
# teardown-worktree.ps1 (drops just that branch's database, leaves the server running).
. (Join-Path $PSScriptRoot '_common.ps1')

if (-not (Test-PgInstalled)) { Write-Note "Postgres binaries not present; nothing to stop."; return }

if (Test-PgRunning) {
  Write-Step "stopping shared Postgres"
  & (Get-PgExe 'pg_ctl') -D $PgData -m fast stop | Out-Null
  Write-Ok "stopped"
} else {
  Write-Ok "server not running"
}
