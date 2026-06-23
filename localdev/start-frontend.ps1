# Run the frontend dev server (Vite) for this worktree.
. (Join-Path $PSScriptRoot '_common.ps1')

$envFile = Join-Path $RepoRoot 'frontend\.env.local'
if (-not (Test-Path $envFile)) {
  Write-Note "frontend\.env.local not found - run .\localdev\bootstrap-worktree.ps1 first (generates it from $SecretsEnv)."
}

# vite.config.ts reads these to set its dev-server port and the /graphql + /admin proxy
# target, so each worktree serves on its own port and proxies to its own backend.
$env:UC_BACKEND_PORT  = $BackendPort
$env:UC_FRONTEND_PORT = $FrontendPort

Write-Step "frontend: vite on http://localhost:$FrontendPort  (proxy -> http://localhost:$BackendPort)"
Push-Location (Join-Path $RepoRoot 'frontend')
try {
  npm run dev
} finally {
  Pop-Location
}
