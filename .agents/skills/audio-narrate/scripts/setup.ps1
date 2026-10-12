# setup.ps1 — prepare audio-narrate on Windows. Safe to run again: it only does what is missing.
#   .\scripts\setup.ps1 -Check     report what is there and what is missing, change nothing
#   .\scripts\setup.ps1            create the Python environment with edge-tts and Piper (about 155 MB)
#   .\scripts\setup.ps1 -Piper     also download the two offline Piper voices (about 126 MB)
#   .\scripts\setup.ps1 -Where     print the Python this skill runs with
param([switch]$Check, [switch]$Piper, [switch]$Where)
$ErrorActionPreference = 'Stop'

$root = if ($env:AGENT_TOOLKIT_HOME) { $env:AGENT_TOOLKIT_HOME } else { Join-Path $HOME '.itqan-agent-toolkit' }
$homeDir = if ($env:AUDIO_NARRATE_HOME) { $env:AUDIO_NARRATE_HOME } else { Join-Path $root 'audio-narrate' }
$venv = Join-Path $homeDir 'venv'
$voices = Join-Path $homeDir 'voices'
$py = Join-Path $venv 'Scripts\python.exe'
# piper-tts is pinned: 1.8.0 fails on its espeak data path; 1.4.2 works.
$pkgs = @('edge-tts', 'piper-tts==1.4.2', 'numpy')
$base = 'https://huggingface.co/rhasspy/piper-voices/resolve/main'
$voiceFiles = @('en/en_US/amy/medium/en_US-amy-medium.onnx', 'ar/ar_JO/kareem/medium/ar_JO-kareem-medium.onnx')

if ($Where) { $py; exit 0 }

function Test-Voices {
  foreach ($v in $voiceFiles) {
    $f = Join-Path $voices (Split-Path $v -Leaf)
    if (-not (Test-Path $f) -or (Get-Item $f).Length -lt 40000000 -or -not (Test-Path "$f.json")) { return $false }
  }
  return $true
}
function Test-Engines { (Test-Path $py) -and ((& $py -c 'import edge_tts, piper, numpy' 2>$null; $LASTEXITCODE) -eq 0) }

if ($Check) {
  $missing = 0
  if (Get-Command ffmpeg -ErrorAction SilentlyContinue) { 'ok       ffmpeg' } else { 'MISSING  ffmpeg   winget install Gyan.FFmpeg'; $missing = 1 }
  if ((Get-Command uv -ErrorAction SilentlyContinue) -or (Get-Command python -ErrorAction SilentlyContinue)) { 'ok       python or uv' } else { 'MISSING  python   winget install Python.Python.3.12'; $missing = 1 }
  if (Test-Engines) { "ok       engines in $venv" } else { 'MISSING  engines  run: .\scripts\setup.ps1'; $missing = 1 }
  if (Test-Voices) { "ok       Piper voices in $voices" } else { 'optional Piper voices not downloaded (offline only, about 126 MB): .\scripts\setup.ps1 -Piper' }
  exit $missing
}

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { 'note: ffmpeg is missing. Install it before narrating: winget install Gyan.FFmpeg' }
New-Item -ItemType Directory -Force $homeDir | Out-Null

if (-not (Test-Path $py)) {
  "creating the Python environment in $venv (edge-tts and Piper, about 155 MB)"
  if (Get-Command uv -ErrorAction SilentlyContinue) {
    uv venv --quiet $venv --python 3.12
    uv pip install --quiet --python $py @pkgs
  } elseif (Get-Command python -ErrorAction SilentlyContinue) {
    python -m venv $venv
    & $py -m pip install -q @pkgs
  } else { throw 'Python 3 is needed: winget install Python.Python.3.12' }
}
if (-not (Test-Engines)) { & $py -m pip install -q @pkgs }

if ($Piper) {
  New-Item -ItemType Directory -Force $voices | Out-Null
  if (Test-Voices) { 'Piper voices already present' } else {
    "downloading two Piper voices, about 126 MB, into $voices"
    foreach ($v in $voiceFiles) {
      $f = Join-Path $voices (Split-Path $v -Leaf)
      Invoke-WebRequest "$base/$v" -OutFile $f
      Invoke-WebRequest "$base/$v.json" -OutFile "$f.json"
    }
  }
}
"ready. python: $py"
