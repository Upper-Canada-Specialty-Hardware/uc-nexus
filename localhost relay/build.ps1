# Build dist/ucnexus-relay.exe locally via PyInstaller. CI (relay-release.yml) does the same on a
# windows-latest runner for releases; this is for local builds / spec iteration.
#
#   .\build.ps1
#
# Requires the dev deps installed (poetry install --with dev). The exe lands in .\dist\.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host "building ucnexus-relay.exe via PyInstaller..."
poetry run pyinstaller --clean --noconfirm ucnexus-relay.spec

$exe = Join-Path $PSScriptRoot "dist\ucnexus-relay.exe"
if (Test-Path $exe) {
    Write-Host "built: $exe"
} else {
    Write-Error "build did not produce $exe"
    exit 1
}
