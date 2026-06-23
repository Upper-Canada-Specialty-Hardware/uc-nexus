# Run the backend dev server (FastAPI + GraphQL) on http://localhost:8000.
. (Join-Path $PSScriptRoot '_common.ps1')

$envFile = Join-Path $RepoRoot 'backend\.env'
if (-not (Test-Path $envFile)) {
  Write-Note "backend\.env not found - copy backend\.env.example to backend\.env and set CLERK_SECRET_KEY."
}

# Pin the DB to the portable Postgres regardless of .env (load_dotenv does not override real env vars).
$env:DATABASE_URL = $DatabaseUrl

Write-Step "backend: uvicorn on http://localhost:8000"
Push-Location (Join-Path $RepoRoot 'backend')
try {
  poetry run uvicorn main:app --reload
} finally {
  Pop-Location
}
