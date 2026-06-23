# Run the frontend dev server (Vite) on http://localhost:5173.
. (Join-Path $PSScriptRoot '_common.ps1')

$envFile = Join-Path $RepoRoot 'frontend\.env.local'
if (-not (Test-Path $envFile)) {
  Write-Note "frontend\.env.local not found - copy frontend\.env.local.example to frontend\.env.local and set VITE_CLERK_PUBLISHABLE_KEY."
}

Write-Step "frontend: vite on http://localhost:5173"
Push-Location (Join-Path $RepoRoot 'frontend')
try {
  npm run dev
} finally {
  Pop-Location
}
