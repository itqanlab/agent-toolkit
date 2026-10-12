# setup-deps.ps1 — check for what this skill needs, and offer to install what is missing.
#
#   node         required, version 18 or newer. The guard script is written in it.
#   higgsfield   required. The official Higgsfield command line tool (npm @higgsfield/cli).
#
# Usage: .\scripts\setup-deps.ps1 [-Check] [-Yes]
#   -Check   report status and exit; never installs anything
#   -Yes     install without asking (for non-interactive and agent use)
#
# Nothing is installed without either a confirmation or an explicit -Yes. Signing in is
# not done here: the user runs `higgsfield auth login` once, which opens the browser.

[CmdletBinding()]
param(
  [switch]$Check,
  [switch]$Yes
)

$ErrorActionPreference = 'Stop'
$MinMajor = 18

function Test-Node {
  $node = Get-Command node -ErrorAction SilentlyContinue
  if (-not $node) { Write-Host "node         MISSING"; return $false }
  $version = (& node -v) -replace '^v', ''
  $major = [int]($version -split '\.')[0]
  if ($major -lt $MinMajor) { Write-Host "node         TOO OLD - found v$version, need v$MinMajor or newer"; return $false }
  Write-Host "node         ok (v$version)"
  return $true
}

function Test-Higgsfield {
  $hf = Get-Command higgsfield -ErrorAction SilentlyContinue
  if (-not $hf) { Write-Host "higgsfield   MISSING"; return $false }
  $v = (& higgsfield version 2>$null | Select-Object -First 1)
  Write-Host "higgsfield   ok ($v)"
  return $true
}

$nodeOk = Test-Node
$hfOk = Test-Higgsfield

if ($nodeOk -and $hfOk) {
  if (-not $Check) {
    Write-Host ""
    Write-Host "Everything this skill needs is installed. If you have not signed in yet, run:"
    Write-Host "    higgsfield auth login"
  }
  exit 0
}
if ($Check) { exit 1 }

Write-Host ""
if (-not $nodeOk) {
  Write-Host "Node $MinMajor or newer is needed first."
  Write-Host "  Download the installer:  https://nodejs.org/en/download"
  Write-Host "  Or, if you have winget:  winget install OpenJS.NodeJS.LTS"
  Write-Host "Then run this again."
  exit 1
}

$cmd = 'npm install -g @higgsfield/cli'
Write-Host "The Higgsfield command line tool can be installed with:"
Write-Host ""
Write-Host "    $cmd"
Write-Host ""

if (-not $Yes) {
  if (-not [Environment]::UserInteractive -or [Console]::IsInputRedirected) {
    Write-Host "Not running interactively. Re-run with -Yes to install, or run the command above yourself."
    exit 1
  }
  $answer = Read-Host 'Run it now? [y/N]'
  if ($answer -notmatch '^(y|yes)$') { Write-Host "Nothing installed."; exit 1 }
}

& npm install -g '@higgsfield/cli'

Write-Host ""
if (Test-Higgsfield) {
  Write-Host ""
  Write-Host "Done. Now sign in once (it opens the browser):"
  Write-Host "    higgsfield auth login"
} else {
  Write-Host ""
  Write-Host "higgsfield is still not on the PATH. Open a new terminal and run this again."
  exit 1
}
