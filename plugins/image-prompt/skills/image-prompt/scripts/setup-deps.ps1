# setup.ps1 — check for what this skill needs, and offer to install what is missing.
#
#   node   required, version 18 or newer. Every script here is written in it.
#
# Usage: .\scripts\setup.ps1 [-Check] [-Yes]
#   -Check   report status and exit; never installs anything
#   -Yes     install without asking (for non-interactive and agent use)
#
# Nothing is installed without either a confirmation or an explicit -Yes.

[CmdletBinding()]
param(
  [switch]$Check,
  [switch]$Yes
)

$ErrorActionPreference = 'Stop'
$MinMajor = 18

function Test-Node {
  $node = Get-Command node -ErrorAction SilentlyContinue
  if (-not $node) {
    Write-Host "node     MISSING"
    return $false
  }
  $version = (& node -v) -replace '^v', ''
  $major = [int]($version -split '\.')[0]
  if ($major -lt $MinMajor) {
    Write-Host "node     TOO OLD - found v$version, need v$MinMajor or newer"
    return $false
  }
  Write-Host "node     ok (v$version)"
  return $true
}

function Show-ManualInstructions {
  Write-Host ""
  Write-Host "Install Node $MinMajor or newer, then run this again."
  Write-Host ""
  Write-Host "  Download the installer:  https://nodejs.org/en/download"
  Write-Host "  Or, if you have winget:  winget install OpenJS.NodeJS.LTS"
}

if (Test-Node) {
  if (-not $Check) {
    Write-Host ""
    Write-Host "Everything this skill needs is already installed."
  }
  exit 0
}

if ($Check) { exit 1 }

$winget = Get-Command winget -ErrorAction SilentlyContinue
if (-not $winget) {
  Show-ManualInstructions
  exit 1
}

$cmd = "winget install --id OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements"
Write-Host ""
Write-Host "Node is needed and can be installed with:"
Write-Host ""
Write-Host "    $cmd"
Write-Host ""

if (-not $Yes) {
  # A non-interactive host (an agent running this) must not block on a prompt.
  if ([Console]::IsInputRedirected) {
    Write-Host "Not running interactively. Re-run with -Yes to install, or run the command above yourself."
    exit 1
  }
  $answer = Read-Host "Run it now? [y/N]"
  if ($answer -notmatch '^(y|yes)$') {
    Write-Host "Nothing installed."
    exit 1
  }
}

Invoke-Expression $cmd

Write-Host ""
Write-Host "Node was installed. Open a new terminal so the PATH change takes effect, then run this again to confirm."
