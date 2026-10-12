#!/usr/bin/env bash
# setup-deps.sh — check for what audio-transcribe needs, and offer to install what is missing.
#
#   ffmpeg    required. Decodes any audio or video into the format Whisper reads.
#   whisper   required. A local speech-to-text engine (mlx, ctranslate2 or openai).
#   yt-dlp    optional. Only for links to YouTube and other sites.
#
# Usage: sh scripts/setup-deps.sh [--check] [--yes] [--with-whisper] [--whisper-engine E] [--with-ytdlp]
#   --check            report status and exit; never installs anything
#   --yes              install without asking (for agents and scripts)
#   --with-whisper     install a Whisper engine if none is present (the default plan does)
#   --whisper-engine E force an engine: mlx | ctranslate2 | openai
#   --with-ytdlp       also install yt-dlp
#
# Every engine is free, open source and runs on this machine. "openai-whisper" is the
# MIT-licensed model OpenAI published in 2022, not the OpenAI service. Installing an
# engine does not download a model: the first transcription says how big the model is
# and asks before downloading it.
#
# Nothing is installed without a confirmation or an explicit --yes.
set -euo pipefail

CHECK_ONLY=0; ASSUME_YES=0; ENGINE=""; WANT_YTDLP=0
while [ $# -gt 0 ]; do
  case "$1" in
    --check)          CHECK_ONLY=1; shift;;
    --yes|-y)         ASSUME_YES=1; shift;;
    --with-whisper)   shift;;
    --whisper-engine) ENGINE="${2:?}"; shift 2;;
    --with-ytdlp)     WANT_YTDLP=1; shift;;
    -h|--help)        sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done

have() { command -v "$1" >/dev/null 2>&1; }

case "$(uname -s)" in
  Darwin) OS_NAME="macOS";;
  Linux)  OS_NAME="Linux";;
  MINGW*|MSYS*|CYGWIN*) OS_NAME="Windows";;
  *) OS_NAME="$(uname -s)";;
esac

PM=""
for m in brew apt-get dnf pacman zypper apk; do have "$m" && { PM="$m"; break; }; done
PIP=""
for m in pipx pip3 pip; do have "$m" && { PIP="$m"; break; }; done
SUDO=""
if [ "$(id -u)" != "0" ] && [ -n "$PM" ] && [ "$PM" != "brew" ] && have sudo; then SUDO="sudo "; fi

engine_cmd() { for w in mlx_whisper whisper-ctranslate2 whisper; do have "$w" && { echo "$w"; return; }; done; echo ""; }
# The fastest engine for the hardware. All are free and local.
pick_engine() {
  [ -n "$ENGINE" ] && { echo "$ENGINE"; return; }
  if [ "$OS_NAME" = "macOS" ] && [ "$(uname -m)" = "arm64" ]; then echo mlx; else echo ctranslate2; fi
}

FF=0; YT=0; have ffmpeg && have ffprobe && FF=1; have yt-dlp && YT=1
WH="$(engine_cmd)"

row() { printf '  %-9s %-8s %s\n' "$1" "$2" "$3"; }
echo "audio-transcribe: dependency check"
echo "  platform  $OS_NAME${PM:+ · $PM}"
echo
row ffmpeg  "$([ $FF -eq 1 ] && echo ok || echo MISSING)" "required: decodes any audio or video"
row whisper "$([ -n "$WH" ] && echo ok || echo MISSING)" "$([ -n "$WH" ] && echo "$WH" || echo "required: local speech to text (would install $(pick_engine))")"
row yt-dlp  "$([ $YT -eq 1 ] && echo ok || echo '-')" "optional: links to YouTube and 1750+ other sites"
echo

MISSING=()
[ $FF -eq 0 ] && MISSING+=(ffmpeg)
[ -z "$WH" ] && MISSING+=(whisper)
[ $WANT_YTDLP -eq 1 ] && [ $YT -eq 0 ] && MISSING+=(yt-dlp)

if [ ${#MISSING[@]} -eq 0 ]; then
  echo "Everything audio-transcribe needs is installed."
  [ $YT -eq 0 ] && echo "Tip: --with-ytdlp adds links to YouTube and other sites."
  exit 0
fi
if [ "$CHECK_ONLY" -eq 1 ]; then
  echo "Missing: ${MISSING[*]}"; echo "Run without --check to install."; exit 1
fi

if [ "$OS_NAME" = "Windows" ]; then
  echo "Missing: ${MISSING[*]}"
  echo "On Windows, install with:"
  echo "  winget install Gyan.FFmpeg ; winget install yt-dlp.yt-dlp"
  echo "  pip install whisper-ctranslate2"
  exit 1
fi

CMDS=()
for dep in "${MISSING[@]}"; do
  case "$dep:$PM" in
    ffmpeg:brew)    CMDS+=("brew install ffmpeg");;
    ffmpeg:apt-get) CMDS+=("${SUDO}apt-get update" "${SUDO}apt-get install -y ffmpeg");;
    ffmpeg:dnf)     CMDS+=("${SUDO}dnf install -y ffmpeg");;
    ffmpeg:pacman)  CMDS+=("${SUDO}pacman -S --noconfirm ffmpeg");;
    ffmpeg:zypper)  CMDS+=("${SUDO}zypper install -y ffmpeg");;
    ffmpeg:apk)     CMDS+=("${SUDO}apk add ffmpeg");;
    ffmpeg:*)       echo "No install rule for ffmpeg here: https://ffmpeg.org/download.html"; exit 1;;
    yt-dlp:brew)    CMDS+=("brew install yt-dlp");;
    yt-dlp:*)       CMDS+=("${PIP:-pip3} install $([ "$PIP" = pipx ] || echo '--user --upgrade ')yt-dlp");;
    whisper:*)
      case "$(pick_engine)" in
        mlx) PKG=mlx-whisper;; ctranslate2) PKG=whisper-ctranslate2;; openai) PKG=openai-whisper;;
        *) echo "unknown --whisper-engine: $ENGINE (use mlx, ctranslate2 or openai)" >&2; exit 2;;
      esac
      [ -n "$PIP" ] || { echo "Python's pip is needed to install $PKG. Install Python 3 first: https://www.python.org/downloads/"; exit 1; }
      CMDS+=("$PIP install $([ "$PIP" = pipx ] || echo '--user --upgrade ')$PKG");;
  esac
done

echo "Missing: ${MISSING[*]}"
echo "Planned commands:"
for c in "${CMDS[@]}"; do echo "  $c"; done
echo
if [ "$ASSUME_YES" -ne 1 ]; then
  [ -t 0 ] || { echo "Not an interactive terminal. Re-run with --yes to install these."; exit 1; }
  printf 'Run them now? [y/N] '; read -r reply
  case "$reply" in [yY]*) ;; *) echo "Nothing installed."; exit 1;; esac
fi
for c in "${CMDS[@]}"; do
  echo "→ $c"
  eval "$c" || { echo "Failed: $c" >&2; exit 1; }
done
echo; echo "Re-checking…"
exec bash "$0" --check
