<#
.SYNOPSIS
  Install these skills for any Agent Skills compatible agent (Windows).

.DESCRIPTION
  Default target is ~\.agents\skills — the vendor-neutral path read by Codex, OpenCode,
  Cursor, Gemini CLI, GitHub Copilot, Amp and Goose. Claude Code is the one agent that
  does NOT read it; use -Claude, or its plugin marketplace. See docs/COMPATIBILITY.md.

  Copies by default. -Link uses a directory JUNCTION rather than a symbolic link,
  because junctions need no administrator rights and no Developer Mode, while Windows
  symlinks need one or the other.

.EXAMPLE
  .\scripts\install.ps1
  .\scripts\install.ps1 -Detect
  .\scripts\install.ps1 watch-video -Link -Force
  .\scripts\install.ps1 -Claude
  .\scripts\install.ps1 -Project
#>
[CmdletBinding()]
param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$Skills = @(),
  [switch]$Project,
  [switch]$Claude,
  [switch]$All,
  [string]$Target,
  [switch]$Link,
  [switch]$Force,
  [switch]$DryRun,
  [switch]$Detect
)

$ErrorActionPreference = 'Stop'
$repoRoot   = Split-Path -Parent $PSScriptRoot
$skillsRoot = Join-Path $repoRoot 'skills'
$neutral    = Join-Path $HOME '.agents\skills'
$claudeDir  = Join-Path $HOME '.claude\skills'

if (-not (Test-Path $skillsRoot)) { throw "No skills/ directory found at $skillsRoot" }

# ---------------------------------------------------------------- agent detection
$agentDefs = @(
  @{ Label = 'Claude Code';    Probe = 'claude';   Dir = "$HOME\.claude";         Own = $claudeDir }
  @{ Label = 'Codex';          Probe = 'codex';    Dir = "$HOME\.codex";          Own = $null }
  @{ Label = 'OpenCode';       Probe = 'opencode'; Dir = "$HOME\.config\opencode"; Own = "$HOME\.config\opencode\skills" }
  @{ Label = 'Cursor';         Probe = 'cursor';   Dir = "$HOME\.cursor";         Own = "$HOME\.cursor\skills" }
  @{ Label = 'Gemini CLI';     Probe = 'gemini';   Dir = "$HOME\.gemini";         Own = "$HOME\.gemini\skills" }
  @{ Label = 'GitHub Copilot'; Probe = 'copilot';  Dir = "$HOME\.copilot";        Own = "$HOME\.copilot\skills" }
  @{ Label = 'Amp';            Probe = 'amp';      Dir = "$HOME\.config\amp";     Own = "$HOME\.config\amp\skills" }
  @{ Label = 'Goose';          Probe = 'goose';    Dir = "$HOME\.config\goose";   Own = "$HOME\.config\goose\skills" }
)

$detected = @()
foreach ($a in $agentDefs) {
  $hasCmd = [bool](Get-Command $a.Probe -ErrorAction SilentlyContinue)
  if ($hasCmd -or (Test-Path $a.Dir)) { $detected += $a }
}

if ($Detect) {
  Write-Host 'Detected agents on this machine:'
  if ($detected.Count -eq 0) { Write-Host '  (none found)' }
  foreach ($a in $detected) {
    if ($a.Label -eq 'Claude Code') {
      Write-Host ("  {0,-16} does NOT read the neutral path - use the marketplace or -Claude" -f $a.Label)
    } elseif ($null -eq $a.Own) {
      Write-Host ("  {0,-16} reads {1}" -f $a.Label, $neutral)
    } else {
      Write-Host ("  {0,-16} reads {1} (and {2})" -f $a.Label, $neutral, $a.Own)
    }
  }
  exit 0
}

# ---------------------------------------------------------------- resolve targets
$targets = @()
if ($Target)      { $targets += $Target }
elseif ($Project) { $targets += (Join-Path (Get-Location) '.agents\skills') }
else {
  $targets += $neutral
  if ($Claude) { $targets += $claudeDir }
  if ($All) {
    foreach ($a in $detected) {
      if ($null -ne $a.Own -and $targets -notcontains $a.Own) { $targets += $a.Own }
    }
  }
}

$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$installed = 0; $skipped = 0

foreach ($target in $targets) {
  Write-Host "-> $target"
  if (-not $DryRun) { New-Item -ItemType Directory -Force -Path $target | Out-Null }
  # Claude Code loads a skill folder containing .claude-plugin\ as a full plugin, so keep
  # it there. Every other agent ignores it, so strip it to stay clean.
  $keepPluginDir = $target.TrimEnd('\') -like '*\.claude\skills'

  Get-ChildItem -Path $skillsRoot -Directory | ForEach-Object {
    $name = $_.Name
    $src  = $_.FullName
    if (-not (Test-Path (Join-Path $src 'SKILL.md'))) { return }
    if ($Skills.Count -gt 0 -and $Skills -notcontains $name) { return }

    $dst = Join-Path $target $name

    if (Test-Path $dst) {
      if ($Force) {
        Write-Host "    replace  $name (backup -> $name.bak-$ts)"
        if (-not $DryRun) { Move-Item -Path $dst -Destination "$dst.bak-$ts" }
      } else {
        Write-Host "    SKIP     $name - exists (re-run with -Force to replace)"
        $script:skipped++
        return
      }
    }

    if ($Link) {
      Write-Host "    junction $name"
      if (-not $DryRun) { New-Item -ItemType Junction -Path $dst -Target $src | Out-Null }
    } else {
      Write-Host "    copy     $name"
      if (-not $DryRun) {
        Copy-Item -Path $src -Destination $dst -Recurse
        if (-not $keepPluginDir) {
          $pluginDir = Join-Path $dst '.claude-plugin'
          if (Test-Path $pluginDir) { Remove-Item -Recurse -Force $pluginDir }
        }
      }
    }
    $script:installed++
  }
}

# ---------------------------------------------------------------- coverage report
Write-Host ''
Write-Host ("installed: {0}   skipped: {1}   mode: {2}" -f $installed, $skipped, $(if ($Link) { 'junction' } else { 'copy' }))
if ($DryRun) { Write-Host '(dry run - nothing changed)' }
Write-Host ''

$coveredNeutral = $targets -contains $neutral
if ($detected.Count -gt 0) {
  Write-Host 'Coverage for agents detected on this machine:'
  foreach ($a in $detected) {
    $ok = $true
    if ($a.Label -eq 'Claude Code')      { $ok = $targets -contains $claudeDir }
    elseif (-not $coveredNeutral)        { $ok = ($null -ne $a.Own) -and ($targets -contains $a.Own) }
    if ($ok) { Write-Host ("  [ok] {0}" -f $a.Label) }
    else     { Write-Host ("  [--] {0} - not covered by this install" -f $a.Label) }
  }
  Write-Host ''
}

if (-not $Claude -and -not $Project -and -not $Target) {
  Write-Host "Claude Code does not read $neutral. Its native channel is better anyway:"
  Write-Host '  /plugin marketplace add itqanlab/agent-toolkit'
  Write-Host '  Or copy into ~\.claude\skills with: .\scripts\install.ps1 -Claude'
}
