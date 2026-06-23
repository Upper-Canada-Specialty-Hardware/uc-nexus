# Reset THIS branch's database: drop it, recreate it, re-migrate. The shared cluster and
# every other branch's database are left untouched (the server stays up).
# For day-to-day data resets, prefer the in-app "drop and rebuild schema" action.
. (Join-Path $PSScriptRoot '_common.ps1')

Write-Note "This drops and rebuilds the '$PgDbName' database (branch '$Branch'). Other branches are untouched."
$env:PGPASSWORD = $PgPassword

if (-not (Test-PgRunning)) {
  Write-Note "shared server not running - starting it first."
} else {
  # Drop the branch DB. Fails if the backend for this worktree is still connected.
  & (Get-PgExe 'dropdb') -h localhost -p $PgPort -U $PgUser --if-exists $PgDbName *> $null
  if ($LASTEXITCODE -eq 0) { Write-Ok "dropped '$PgDbName'" }
  else { Write-Note "dropdb exit $LASTEXITCODE - stop this worktree's backend, then re-run." }
}

# Recreate + migrate (start-db createdb's the branch DB and runs alembic upgrade head).
& (Join-Path $PSScriptRoot 'start-db.ps1')
exit 0
