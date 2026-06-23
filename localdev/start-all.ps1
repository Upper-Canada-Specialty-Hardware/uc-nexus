# One-shot: bring up Postgres, then launch backend + frontend each in its own window.
. (Join-Path $PSScriptRoot '_common.ps1')

# 1. Database (blocks until ready + migrated; throws if the binaries zip is missing).
& (Join-Path $PSScriptRoot 'start-db.ps1')

# 2. Backend + frontend in separate windows so their logs stay readable.
$ps = Get-PsExe
$backend  = '"' + (Join-Path $PSScriptRoot 'start-backend.ps1') + '"'
$frontend = '"' + (Join-Path $PSScriptRoot 'start-frontend.ps1') + '"'

Write-Step "launching backend + frontend in new windows"
Start-Process -FilePath $ps -ArgumentList '-NoExit','-File',$backend
Start-Process -FilePath $ps -ArgumentList '-NoExit','-File',$frontend

Write-Host ""
Write-Ok "backend : http://localhost:8000  (GraphQL at /graphql)"
Write-Ok "frontend: http://localhost:5173"
Write-Host ""
Write-Host "  first run only: backend needs 'poetry install', frontend needs 'npm ci'." -ForegroundColor DarkGray
