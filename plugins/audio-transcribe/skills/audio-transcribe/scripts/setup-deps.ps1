# setup-deps.ps1 — check for what audio-transcribe needs on Windows, and offer to install it.
#
#   ffmpeg    required. Decodes any audio or video.
#   whisper   required. A local speech-to-text engine. whisper-ctranslate2 is the one
#             offered here: free, local, and about 4x faster than the reference on a CPU.
#   yt-dlp    optional. Only for links to YouTube and other sites.
#   bash      required to run scripts/transcribe.sh: Git Bash or WSL.
#
# Usage: .\scripts\setup-deps.ps1 [-Check] [-Yes] [-WithYtdlp]
param([switch]$Check, [switch]$Yes, [switch]$WithYtdlp)

function Have($name) { [bool](Get-Command $name -ErrorAction SilentlyContinue) }

$engine = @('whisper-ctranslate2', 'whisper') | Where-Object { Have $_ } | Select-Object -First 1
$rows = @(
  @{ n = 'ffmpeg';  ok = (Have 'ffmpeg') -and (Have 'ffprobe'); why = 'required: decodes any audio or video' },
  @{ n = 'whisper'; ok = [bool]$engine; why = $(if ($engine) { $engine } else { 'required: local speech to text' }) },
  @{ n = 'bash';    ok = (Have 'bash'); why = 'required: Git Bash or WSL runs scripts/transcribe.sh' },
  @{ n = 'yt-dlp';  ok = (Have 'yt-dlp'); why = 'optional: links to YouTube and other sites' }
)
Write-Host 'audio-transcribe: dependency check'
foreach ($r in $rows) { Write-Host ('  {0,-9} {1,-8} {2}' -f $r.n, $(if ($r.ok) { 'ok' } else { 'MISSING' }), $r.why) }
Write-Host ''

$plan = @()
if (-not $rows[0].ok) { $plan += 'winget install --id Gyan.FFmpeg -e' }
if (-not $rows[1].ok) {
  if (Have 'pip') { $plan += 'pip install --user --upgrade whisper-ctranslate2' }
  else { Write-Host 'Python 3 is needed first for the Whisper engine: winget install --id Python.Python.3.12 -e' }
}
if (-not $rows[2].ok) { $plan += 'winget install --id Git.Git -e' }
if ($WithYtdlp -and -not $rows[3].ok) { $plan += 'winget install --id yt-dlp.yt-dlp -e' }

if ($plan.Count -eq 0) { Write-Host 'Everything audio-transcribe needs is installed.'; exit 0 }
if ($Check) { Write-Host 'Missing items. Run without -Check to install.'; exit 1 }

Write-Host 'Planned commands:'
$plan | ForEach-Object { Write-Host "  $_" }
if (-not $Yes) {
  $reply = Read-Host 'Run them now? [y/N]'
  if ($reply -notmatch '^[yY]') { Write-Host 'Nothing installed.'; exit 1 }
}
foreach ($c in $plan) {
  Write-Host "-> $c"
  Invoke-Expression $c
  if ($LASTEXITCODE -ne 0) { Write-Error "Failed: $c"; exit 1 }
}
Write-Host 'Done. Open a new terminal so the new commands are on PATH, then run this again with -Check.'
