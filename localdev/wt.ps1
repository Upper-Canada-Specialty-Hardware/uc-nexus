# Thin loader for the worktree-localdev engine. Identical in every repo - it only finds the shared
# engine and dispatches. All per-repo specifics live in localdev/config.psd1.
#
#   .\localdev\wt.ps1 bootstrap-machine | bootstrap-worktree | start-all | start-service NAME |
#                     start-db | stop-db | reset-db | teardown
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot

# Find the shared engine: WT_LOCALDEV_DIR env override, else the conventional clone location.
$engineDir = if ($env:WT_LOCALDEV_DIR) { $env:WT_LOCALDEV_DIR } else { Join-Path $env:USERPROFILE 'Documents\worktree-localdev' }
$engine = Join-Path $engineDir 'wt-engine.ps1'
if (-not (Test-Path $engine)) {
  throw "worktree-localdev engine not found at $engine.`n  Clone https://github.com/Xilous/worktree-localdev and/or set `$env:WT_LOCALDEV_DIR to its path."
}
. $engine

$cmd  = if ($args.Count -ge 1) { $args[0] } else { 'help' }
$rest = if ($args.Count -ge 2) { $args[1..($args.Count - 1)] } else { @() }
Invoke-Wt -RepoRoot $repoRoot -ConfigPath (Join-Path $PSScriptRoot 'config.psd1') -Command $cmd -Rest $rest
