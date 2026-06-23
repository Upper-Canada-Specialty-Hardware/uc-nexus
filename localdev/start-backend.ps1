# Run the backend dev server (FastAPI + GraphQL) for this worktree.
. (Join-Path $PSScriptRoot '_common.ps1')

$envFile = Join-Path $RepoRoot 'backend\.env'
if (-not (Test-Path $envFile)) {
  Write-Note "backend\.env not found - run .\localdev\bootstrap-worktree.ps1 first (generates it from $SecretsEnv)."
}

# Pin the DB to this branch's database regardless of .env (load_dotenv does not override
# real env vars), so the backend can't accidentally talk to another branch's data.
$env:DATABASE_URL = $DatabaseUrl

Write-Step "backend: uvicorn on http://localhost:$BackendPort  (db: $PgDbName)"
Push-Location (Join-Path $RepoRoot 'backend')
try {
  poetry run uvicorn main:app --reload --port $BackendPort
} finally {
  Pop-Location
}
