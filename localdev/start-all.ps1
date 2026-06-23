# One-shot: ensure this branch's DB is up + migrated, then launch backend + frontend
# each in its own window on this worktree's ports.
. (Join-Path $PSScriptRoot '_common.ps1')

# Warn early if this worktree hasn't been bootstrapped (env files generated + deps installed).
if (-not (Test-Path (Join-Path $RepoRoot 'backend\.env')) -or
    -not (Test-Path (Join-Path $RepoRoot 'frontend\.env.local'))) {
  Write-Note "env files missing - run .\localdev\bootstrap-worktree.ps1 first."
}

# 1. Database: shared server; ensures THIS branch's database exists + is migrated.
& (Join-Path $PSScriptRoot 'start-db.ps1')

# 2. Backend + frontend in separate windows so their logs stay readable.
$ps = Get-PsExe
$backend  = '"' + (Join-Path $PSScriptRoot 'start-backend.ps1') + '"'
$frontend = '"' + (Join-Path $PSScriptRoot 'start-frontend.ps1') + '"'

Write-Step "launching backend + frontend in new windows"
Start-Process -FilePath $ps -ArgumentList '-NoExit', '-File', $backend
Start-Process -FilePath $ps -ArgumentList '-NoExit', '-File', $frontend

Write-Host ""
Write-Ok "app     : http://localhost:$FrontendPort"
Write-Ok "backend : http://localhost:$BackendPort  (GraphQL at /graphql)"
Write-Ok "database: $PgDbName  (branch '$Branch')"
exit 0
