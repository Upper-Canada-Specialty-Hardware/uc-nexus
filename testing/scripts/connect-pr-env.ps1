<#
.SYNOPSIS
Point the workstation relay at a PR environment so it can be click-through tested, or unpoint it.

.DESCRIPTION
A PR environment is relay-disconnected by default, and with no relay there are no projects - so
nearly the whole app is unreachable. This connects one. See "Connect a PR environment for full
click-through testing" in testing/PR-ENVIRONMENT.md for what each step is and how to diagnose it by hand.

This exists as a script rather than only prose because prose about code drifts: the runbook claimed
for months that adding a channel needed a relay restart, which stopped being true at #456 and cost a
session. A script is either run and correct or run and loudly broken.

Only ever writes [channel] extra_backend_urls. It never touches backend_url: production's URL comes
from the relay's baked default, and retyping it with one character wrong silently demotes the
production channel to the TUBC sandbox pin with no loud failure.

.PARAMETER PrNumber
The GitHub PR number. The Railway environment is uc-nexus-pr-<PrNumber>.

.PARAMETER Disconnect
Remove this PR's URL from the channel list instead of adding it. Do this when the PR closes.

.EXAMPLE
./connect-pr-env.ps1 511
.EXAMPLE
./connect-pr-env.ps1 511 -Disconnect
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [int] $PrNumber,
    [switch] $Disconnect
)

$ErrorActionPreference = 'Stop'

$ConfigPath = Join-Path $env:LOCALAPPDATA 'UCNexusRelay\config.toml'
$LogPath    = Join-Path $env:LOCALAPPDATA 'UCNexusRelay\relay.log'
$EnvName    = "uc-nexus-pr-$PrNumber"
$BackendUrl = "https://backend-uc-nexus-pr-$PrNumber.up.railway.app"
$ChannelUrl = "wss://backend-uc-nexus-pr-$PrNumber.up.railway.app/relay-link"

function Step($n, $text) { Write-Host "`n[$n] $text" -ForegroundColor Cyan }
function Ok($text)       { Write-Host "    OK   $text" -ForegroundColor Green }
function Warn($text)     { Write-Host "    WARN $text" -ForegroundColor Yellow }
function Fail($text)     { Write-Host "    FAIL $text" -ForegroundColor Red }

# --- 1. the Railway environment ------------------------------------------------------------------
# Named uc-nexus-pr-<N>, not pr-<N>; the CLI's "not found" for the latter reads like it is missing.
Step 1 "Railway environment $EnvName"
$envJson = railway environment list --json 2>&1 | Out-String
try { $envs = ($envJson | ConvertFrom-Json).environments } catch { $envs = $null }
$target = $envs | Where-Object { $_.name -eq $EnvName }
if (-not $target) {
    Fail "no environment named $EnvName. Open PRs get one automatically; drafts do not."
    Write-Host "         environments: $(($envs | ForEach-Object { $_.name }) -join ', ')"
    exit 1
}
Ok "found ($($target.id))"

# --- 2/3. the two backend variables ---------------------------------------------------------------
# TESTING_SIGN_IN_SECRET_HASH mints a session; RELAY_SEED_SECRET_HASH gets the relay handshake past
# the 4403 a fresh preview database would otherwise answer. Both are reads here - setting either is a
# deliberate act with its own consequences, so this reports rather than fixes.
Step 2 'backend variables'
$varJson = railway variables --environment $EnvName --service backend --json 2>&1 | Out-String
try { $vars = $varJson | ConvertFrom-Json } catch { $vars = $null }
if (-not $vars) {
    Warn 'could not read variables; skipping the check (the channel step below still works)'
} else {
    foreach ($name in 'TESTING_SIGN_IN_SECRET_HASH', 'RELAY_SEED_SECRET_HASH') {
        if ($vars.PSObject.Properties.Name -contains $name -and $vars.$name) { Ok "$name set" }
        else { Warn "$name NOT set - see testing/PR-ENVIRONMENT.md, runbook steps 2 and 3" }
    }
}

# --- 4. the channel list --------------------------------------------------------------------------
Step 3 "$(if ($Disconnect) { 'removing' } else { 'adding' }) the channel in config.toml"
if (-not (Test-Path $ConfigPath)) { Fail "no relay config at $ConfigPath - is the relay installed?"; exit 1 }

$toml = [System.IO.File]::ReadAllText($ConfigPath)

# Collect the URLs currently listed, so this is additive rather than a blind overwrite: another PR
# may legitimately be connected at the same time.
$existing = @()
$m = [regex]::Match($toml, '(?m)^\s*extra_backend_urls\s*=\s*\[(?<body>[^\]]*)\]')
if ($m.Success) {
    $existing = [regex]::Matches($m.Groups['body'].Value, '"([^"]+)"') | ForEach-Object { $_.Groups[1].Value }
}

$wanted = @($existing | Where-Object { $_ -ne $ChannelUrl })
if (-not $Disconnect) { $wanted += $ChannelUrl }
$wanted = @($wanted | Where-Object { $_ })

$rendered = 'extra_backend_urls = [' + (($wanted | ForEach-Object { '"' + $_ + '"' }) -join ', ') + ']'

if ($m.Success) {
    $toml = $toml.Remove($m.Index, $m.Length).Insert($m.Index, $rendered)
} elseif (-not $Disconnect) {
    if ($toml -notmatch '(?m)^\s*\[channel\]') { $toml = $toml.TrimEnd() + "`r`n`r`n[channel]`r`n" }
    $toml = $toml.TrimEnd() + "`r`n$rendered`r`n"
}

if ($toml -notmatch '(?m)^\s*extra_backend_urls' -and -not $Disconnect) { Fail 'could not write the channel list'; exit 1 }

# UTF-8 with NO BOM. PowerShell 5.1's Set-Content -Encoding utf8 writes one, tomllib then refuses the
# file, and the relay crashes at startup - taking the PRODUCTION channel down with it.
[System.IO.File]::WriteAllText($ConfigPath, $toml, (New-Object System.Text.UTF8Encoding($false)))
Ok "channel list is now: $(if ($wanted) { $wanted -join ', ' } else { '(empty)' })"

# --- 5. wait for the relay to reconcile ------------------------------------------------------------
# #456: run_forever re-reads config.toml on a tick, so this needs no restart. If nothing appears
# within the window below, the relay is not running or the file did not parse.
Step 4 'waiting for the relay to pick it up'
if (-not (Test-Path $LogPath)) { Warn "no relay.log at $LogPath - cannot confirm; check the app header instead"; exit 0 }

$want = if ($Disconnect) { 'removed' } else { 'connected' }
$startLen = (Get-Item $LogPath).Length
$deadline = (Get-Date).AddSeconds(45)
$seen = $false
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 3
    $tail = Get-Content $LogPath -Tail 60 -ErrorAction SilentlyContinue
    if ($Disconnect) {
        if ($tail | Where-Object { $_ -match 'backend channels changed' -and $_ -match [regex]::Escape($ChannelUrl) }) { $seen = $true; break }
    } else {
        if ($tail | Where-Object { $_ -match 'channel connected' -and $_ -match [regex]::Escape($ChannelUrl) }) { $seen = $true; break }
    }
}

if ($seen) {
    Ok "relay reports the channel $want"
    if (-not $Disconnect) {
        Write-Host "`nConnected. Next: sign in and confirm the PO header reads RELAY CONNECTED, then" -ForegroundColor Green
        Write-Host "assign your GP buyer to the project under Admin -> Buyers (runbook step 6)." -ForegroundColor Green
        Write-Host "Backend: $BackendUrl" -ForegroundColor DarkGray
    } else {
        Write-Host "`nDisconnected." -ForegroundColor Green
    }
} else {
    Warn "no confirmation in relay.log within 45s. Check that the relay is running, and that"
    Warn "$LogPath has no TOML parse error (a BOM in config.toml crashes it at startup)."
    if ((Get-Item $LogPath).Length -eq $startLen) { Warn 'the log has not grown at all - the relay is probably not running.' }
    exit 1
}
