# Build the ucnexus-relay ONEDIR bundle locally via PyInstaller and zip it. CI (relay-release.yml) does the
# same on a windows-latest runner for releases; this is for local builds / spec iteration.
#
#   .\build.ps1
#
# Requires the dev deps installed (poetry install --with dev). Produces:
#   .\dist\ucnexus-relay\            the onedir bundle (ucnexus-relay.exe + _internal\)
#   .\dist\ucnexus-relay.zip         that bundle zipped (what the installer/updater extract into app-<build>\)
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host "building the ucnexus-relay onedir bundle via PyInstaller..."
poetry run pyinstaller --clean --noconfirm ucnexus-relay.spec

$appDir = Join-Path $PSScriptRoot "dist\ucnexus-relay"
$exe = Join-Path $appDir "ucnexus-relay.exe"
if (-not (Test-Path $exe)) {
    Write-Error "build did not produce $exe"
    exit 1
}

$zip = Join-Path $PSScriptRoot "dist\ucnexus-relay.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
# zip the CONTENTS of the onedir (exe + _internal at the archive root) so extracting into app-<build>\ lands
# ucnexus-relay.exe directly there.
Compress-Archive -Path (Join-Path $appDir "*") -DestinationPath $zip
Write-Host "built onedir: $appDir"
Write-Host "packaged zip: $zip"
