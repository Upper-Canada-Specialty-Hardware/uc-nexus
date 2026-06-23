# Per-worktree setup: reserve app ports, generate env files from the shared secrets,
# install deps, and create + migrate this branch's database. Run once in a fresh worktree.
. (Join-Path $PSScriptRoot '_common.ps1')

Write-Step "bootstrap worktree: branch '$Branch' -> db '$PgDbName'"

if (-not (Test-Path $SecretsEnv)) {
  throw "secrets.env not found at $SecretsEnv - run .\localdev\bootstrap-machine.ps1 first."
}
$secrets = Read-EnvFile $SecretsEnv

# 1. Reserve a free, stable port pair for this branch (registry at $PortsFile). master
#    pins 8000/5173; other branches get a deterministic pair, bumped past any collision.
$reg = Read-PortsRegistry
if (-not $reg) { $reg = [pscustomobject]@{} }

if ($IsMaster) {
  $bp = 8000; $fp = 5173
} elseif ($reg.PSObject.Properties.Name -contains $PgDbName) {
  $bp = [int]$reg.$PgDbName.backend; $fp = [int]$reg.$PgDbName.frontend
  Write-Ok "reusing reserved ports $bp / $fp"
} else {
  $taken = @{}
  foreach ($p in $reg.PSObject.Properties) { $taken[[int]$p.Value.backend] = $true; $taken[[int]$p.Value.frontend] = $true }
  $off = Get-BranchOffset $Branch
  $bp = $null; $fp = $null
  for ($i = 0; $i -lt 98; $i++) {
    $cand = ($off + $i) % 98
    $b = 8000 + $cand; $f = 5173 + $cand
    if (-not $taken[$b] -and -not $taken[$f] -and (Test-PortFree $b) -and (Test-PortFree $f)) { $bp = $b; $fp = $f; break }
  }
  if (-not $bp) { throw "could not find a free port pair for branch '$Branch'" }
  $reg | Add-Member -NotePropertyName $PgDbName -NotePropertyValue ([pscustomobject]@{ backend = $bp; frontend = $fp }) -Force
  Set-Content -Path $PortsFile -Value ($reg | ConvertTo-Json -Depth 5) -Encoding ascii
  Write-Ok "reserved ports $bp / $fp"
}

# 2. Generate backend\.env (DB pinned to this branch + shared secrets).
$backendEnv = @(
  "DATABASE_URL=$DatabaseUrl",
  "TESTING_ENABLED=true",
  "CLERK_SECRET_KEY=$($secrets['CLERK_SECRET_KEY'])",
  "BUCKET_ENDPOINT=$($secrets['BUCKET_ENDPOINT'])",
  "BUCKET_ACCESS_KEY_ID=$($secrets['BUCKET_ACCESS_KEY_ID'])",
  "BUCKET_SECRET_ACCESS_KEY=$($secrets['BUCKET_SECRET_ACCESS_KEY'])",
  "BUCKET_NAME=$($secrets['BUCKET_NAME'])"
)
Set-Content -Path (Join-Path $RepoRoot 'backend\.env') -Value $backendEnv -Encoding ascii
Write-Ok "wrote backend\.env"

# 3. Generate frontend\.env.local.
Set-Content -Path (Join-Path $RepoRoot 'frontend\.env.local') `
  -Value @("VITE_CLERK_PUBLISHABLE_KEY=$($secrets['VITE_CLERK_PUBLISHABLE_KEY'])") -Encoding ascii
Write-Ok "wrote frontend\.env.local"

# 4. Install deps for this worktree (each checkout has its own node_modules + poetry venv).
Write-Step "poetry install (backend)"
Push-Location (Join-Path $RepoRoot 'backend')
try { poetry install; if ($LASTEXITCODE -ne 0) { throw "poetry install failed" } } finally { Pop-Location }

Write-Step "npm ci (frontend)"
Push-Location (Join-Path $RepoRoot 'frontend')
try { npm ci; if ($LASTEXITCODE -ne 0) { throw "npm ci failed" } } finally { Pop-Location }

# 5. Bring up the shared server + create/migrate this branch's database.
& (Join-Path $PSScriptRoot 'start-db.ps1')

Write-Host ""
Write-Ok "worktree ready. run .\localdev\start-all.ps1 to launch the stack."
Write-Ok "app: http://localhost:$fp   backend: http://localhost:$bp   db: $PgDbName"
exit 0
