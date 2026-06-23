# Ensure the portable Postgres is extracted, initialized, running, and migrated.
. (Join-Path $PSScriptRoot '_common.ps1')

Write-Step "UC Nexus local Postgres"

# 1. Ensure the portable Postgres binaries are present.
if (-not (Test-PgInstalled)) {
  if (-not (Test-Path $LocalDev)) { New-Item -ItemType Directory -Path $LocalDev | Out-Null }
  $zip = Get-ChildItem -Path $LocalDev -Filter 'postgresql-*-windows-x64-binaries.zip' -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $zip) {
    Write-Note "Portable Postgres not found (looked in $LocalDev)."
    Write-Host "  First time on this machine? Run .\localdev\bootstrap-machine.ps1 - it migrates an" -ForegroundColor Yellow
    Write-Host "  existing in-repo .localdev or sets up the shared home for you." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Otherwise, download the Postgres 16 'binaries only' zip (NOT the installer) from:" -ForegroundColor Yellow
    Write-Host "    https://www.enterprisedb.com/download-postgresql-binaries" -ForegroundColor Yellow
    Write-Host "  pick: PostgreSQL 16.x  /  Windows x86-64  /  'zip archive'" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  then drop the file (e.g. postgresql-16.9-1-windows-x64-binaries.zip) into:" -ForegroundColor Yellow
    Write-Host "    $LocalDev" -ForegroundColor Yellow
    Write-Host "  and run this script again." -ForegroundColor Yellow
    throw "Postgres binaries missing."
  }
  Write-Step "extracting $($zip.Name)"
  Expand-Archive -Path $zip.FullName -DestinationPath $LocalDev -Force
  if (-not (Test-PgInstalled)) { throw "Extraction did not produce $PgBin - is this the 'binaries only' build?" }
  Write-Ok "extracted to $PgRoot"
}

$env:PGPASSWORD = $PgPassword

# 2. Initialize the data directory once.
if (-not (Test-Path (Join-Path $PgData 'PG_VERSION'))) {
  Write-Step "initdb (first run)"
  if (Test-Path $PgData) { Remove-Item -Recurse -Force $PgData }
  $pwfile = Join-Path $LocalDev '.initpw'
  Set-Content -Path $pwfile -Value $PgPassword -NoNewline -Encoding ascii
  try {
    & (Get-PgExe 'initdb') -D $PgData -U $PgUser -A scram-sha-256 --pwfile=$pwfile -E UTF8 --locale=C | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "initdb failed (exit $LASTEXITCODE)" }
  } finally {
    Remove-Item $pwfile -Force -ErrorAction SilentlyContinue
  }
  Write-Ok "cluster created at $PgData"
}

# 3. Start the server if not already running.
if (Test-PgRunning) {
  Write-Ok "server already running on port $PgPort"
} else {
  Write-Step "starting server on 127.0.0.1:$PgPort"
  # Launch via Start-Process, not the call operator. When this script's stdout is captured
  # (automation/CI/background task), a postmaster started by `& pg_ctl ... start` inherits the
  # captured pipe, so the launching shell blocks forever - the server is up but the script never
  # returns. Start-Process gives pg_ctl its own detached stdio, so the postmaster never holds our
  # pipe. -W (no wait) returns immediately; the pg_isready loop below confirms readiness.
  $startArgs = "-D `"$PgData`" -l `"$PgLog`" -o `"-p $PgPort`" -W start"
  $proc = Start-Process -FilePath (Get-PgExe 'pg_ctl') -ArgumentList $startArgs -WindowStyle Hidden -PassThru -Wait
  if ($proc.ExitCode -ne 0) { throw "pg_ctl start failed (exit $($proc.ExitCode)) - see $PgLog" }
  Write-Ok "started (log: $PgLog)"
}

# 4. Wait until it accepts connections.
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
  & (Get-PgExe 'pg_isready') -h localhost -p $PgPort -U $PgUser *> $null
  if ($LASTEXITCODE -eq 0) { $ready = $true; break }
  Start-Sleep -Milliseconds 500
}
if (-not $ready) { throw "Postgres did not become ready on port $PgPort - see $PgLog" }

# 5. Create the database if missing (createdb is harmless if it already exists).
& (Get-PgExe 'createdb') -h localhost -p $PgPort -U $PgUser $PgDbName *> $null
if ($LASTEXITCODE -eq 0) { Write-Ok "database '$PgDbName' created" } else { Write-Ok "database '$PgDbName' already present" }

# 6. Apply migrations against the local DB.
Write-Step "alembic upgrade head"
$env:DATABASE_URL = $DatabaseUrl
Push-Location (Join-Path $RepoRoot 'backend')
try {
  poetry run alembic upgrade head
  if ($LASTEXITCODE -ne 0) { throw "alembic upgrade failed (exit $LASTEXITCODE)" }
} finally {
  Pop-Location
}

Write-Ok "Postgres ready: $DatabaseUrl"
