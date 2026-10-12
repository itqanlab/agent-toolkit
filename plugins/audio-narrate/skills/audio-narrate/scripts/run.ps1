# run.ps1 — run an engine with the skill's own Python on Windows.
#   .\scripts\run.ps1 edge  --text "..." --out a.mp3
#   .\scripts\run.ps1 piper --text "..." --out a.wav
$root = if ($env:AGENT_TOOLKIT_HOME) { $env:AGENT_TOOLKIT_HOME } else { Join-Path $HOME '.itqan-agent-toolkit' }
$homeDir = if ($env:AUDIO_NARRATE_HOME) { $env:AUDIO_NARRATE_HOME } else { Join-Path $root 'audio-narrate' }
$py = Join-Path $homeDir 'venv\Scripts\python.exe'
if (-not (Test-Path $py)) { Write-Error 'audio-narrate is not set up yet. Run: .\scripts\setup.ps1'; exit 2 }
$engine = $args[0]; $rest = $args | Select-Object -Skip 1
switch ($engine) {
  'edge' { & $py (Join-Path $PSScriptRoot 'edge.py') @rest; exit $LASTEXITCODE }
  'piper' { & $py (Join-Path $PSScriptRoot 'tts.py') @rest; exit $LASTEXITCODE }
  default { Write-Error 'usage: run.ps1 edge|piper [options]'; exit 2 }
}
