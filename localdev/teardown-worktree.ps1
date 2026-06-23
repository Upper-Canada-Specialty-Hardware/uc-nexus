# After a worktree is merged/abandoned: drop its branch database and release its port
# reservation. The shared server and other worktrees are untouched. No-op on master.
# Stop this worktree's backend first, or the drop fails on an active connection.
. (Join-Path $PSScriptRoot '_common.ps1')

if ($IsMaster) { Write-Note "on master - refusing to drop the canonical 'uc_nexus' database."; return }

Write-Step "teardown worktree: branch '$Branch'  (db '$PgDbName')"
$env:PGPASSWORD = $PgPassword

if (Test-PgRunning) {
  & (Get-PgExe 'dropdb') -h localhost -p $PgPort -U $PgUser --if-exists $PgDbName *> $null
  if ($LASTEXITCODE -eq 0) { Write-Ok "dropped database '$PgDbName'" }
  else { Write-Note "dropdb exit $LASTEXITCODE - is the backend still connected to it? stop it and re-run." }
} else {
  Write-Note "shared server not running - start it and re-run to drop '$PgDbName'."
}

# Release the port reservation.
$reg = Read-PortsRegistry
if ($reg -and ($reg.PSObject.Properties.Name -contains $PgDbName)) {
  $reg.PSObject.Properties.Remove($PgDbName)
  $json = $reg | ConvertTo-Json -Depth 5
  if (-not $json) { $json = '{}' }
  Set-Content -Path $PortsFile -Value $json -Encoding ascii
  Write-Ok "released port reservation"
}

Write-Ok "teardown done."
exit 0
