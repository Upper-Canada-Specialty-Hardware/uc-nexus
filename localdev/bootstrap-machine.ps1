# One-time machine setup for the UC Nexus local runtime. Creates the shared machine-level
# home, migrates any existing in-repo .localdev/ into it, and seeds secrets.env with the
# shared dev keys. Idempotent - safe to re-run. Run once per device.
. (Join-Path $PSScriptRoot '_common.ps1')

Write-Step "UC Nexus machine bootstrap -> $UcHome"
if (-not (Test-Path $UcHome))   { New-Item -ItemType Directory -Path $UcHome   | Out-Null }
if (-not (Test-Path $LocalDev)) { New-Item -ItemType Directory -Path $LocalDev | Out-Null }

# 1. Migrate an existing in-repo .localdev/ (binaries + cluster + log + zip) into the home.
$oldLocalDev = Join-Path $RepoRoot '.localdev'
if ((Test-Path $oldLocalDev) -and -not (Test-Path $PgRoot)) {
  Write-Step "migrating $oldLocalDev -> $LocalDev"
  # Stop a server still running from the old location so its files aren't locked.
  $oldData = Join-Path $oldLocalDev 'pgdata'
  $oldCtl  = Join-Path $oldLocalDev 'pgsql\bin\pg_ctl.exe'
  if ((Test-Path $oldCtl) -and (Test-Path $oldData)) {
    & $oldCtl -D $oldData status *> $null
    if ($LASTEXITCODE -eq 0) { Write-Note "stopping old server before move"; & $oldCtl -D $oldData -m fast stop *> $null }
  }
  foreach ($item in Get-ChildItem -Path $oldLocalDev -Force) {
    Move-Item -Path $item.FullName -Destination (Join-Path $LocalDev $item.Name) -Force
  }
  Write-Ok "moved binaries + cluster into $LocalDev"
} elseif (Test-Path $PgRoot) {
  Write-Ok "postgres already present in $LocalDev"
}

# 2. Seed secrets.env from existing env files (if any), else write a template to fill in.
if (-not (Test-Path $SecretsEnv)) {
  $be = Read-EnvFile (Join-Path $RepoRoot 'backend\.env')
  $fe = Read-EnvFile (Join-Path $RepoRoot 'frontend\.env.local')
  $clerkSecret = if ($be.ContainsKey('CLERK_SECRET_KEY'))             { $be['CLERK_SECRET_KEY'] }             else { 'sk_test_replace_me' }
  $clerkPub    = if ($fe.ContainsKey('VITE_CLERK_PUBLISHABLE_KEY'))   { $fe['VITE_CLERK_PUBLISHABLE_KEY'] }   else { 'pk_test_replace_me' }
  $lines = @(
    '# Shared UC Nexus dev secrets. bootstrap-worktree.ps1 reads these to generate each',
    "# worktree's backend\.env and frontend\.env.local. Paste once per machine; never commit.",
    "CLERK_SECRET_KEY=$clerkSecret",
    "VITE_CLERK_PUBLISHABLE_KEY=$clerkPub",
    "BUCKET_ENDPOINT=$($be['BUCKET_ENDPOINT'])",
    "BUCKET_ACCESS_KEY_ID=$($be['BUCKET_ACCESS_KEY_ID'])",
    "BUCKET_SECRET_ACCESS_KEY=$($be['BUCKET_SECRET_ACCESS_KEY'])",
    "BUCKET_NAME=$($be['BUCKET_NAME'])"
  )
  Set-Content -Path $SecretsEnv -Value $lines -Encoding ascii
  Write-Ok "wrote $SecretsEnv"
  if ($clerkSecret -eq 'sk_test_replace_me' -or $clerkPub -eq 'pk_test_replace_me') {
    Write-Note "fill in CLERK_SECRET_KEY / VITE_CLERK_PUBLISHABLE_KEY in $SecretsEnv"
  }
} else {
  Write-Ok "secrets.env already present"
}

Write-Host ""
Write-Ok "machine bootstrap done."
Write-Ok "next: in each worktree run .\localdev\bootstrap-worktree.ps1"
exit 0
