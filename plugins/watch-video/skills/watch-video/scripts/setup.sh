#!/usr/bin/env bash
# setup.sh — check for what watch-video needs, and offer to install what is missing.
#
#   ffmpeg   required. Extracts frames and reads media metadata.
#   yt-dlp   required for URLs. Downloads the video and its captions.
#   whisper  optional. Generates a transcript when the source has no captions.
#
# Usage: scripts/setup.sh [--check] [--yes] [--with-whisper] [--whisper-engine E]
#   --check            report status and exit; never installs anything
#   --yes              install without asking (for non-interactive and agent use)
#   --with-whisper     also install a local speech-to-text engine
#   --whisper-engine E force an engine: mlx | ctranslate2 | openai
#
# Every engine here is free, open source and runs entirely on this machine.
# None of them call a paid API. "openai-whisper" is the MIT-licensed model
# OpenAI published in 2022, not the OpenAI service.
#
# Nothing is installed without either a confirmation or an explicit --yes.
# Commands that need root are shown in full before they run.
set -euo pipefail

CHECK_ONLY=0; ASSUME_YES=0; WANT_WHISPER=0; ENGINE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --check)          CHECK_ONLY=1; shift;;
    --yes|-y)         ASSUME_YES=1; shift;;
    --with-whisper)   WANT_WHISPER=1; shift;;
    --whisper-engine) ENGINE="$2"; WANT_WHISPER=1; shift 2;;
    -h|--help)        sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done

have() { command -v "$1" >/dev/null 2>&1; }

# ---------------------------------------------------------------- environment

OS="$(uname -s)"
case "$OS" in
  Darwin) OS_NAME="macOS";;
  Linux)  OS_NAME="Linux";;
  MINGW*|MSYS*|CYGWIN*) OS_NAME="Windows";;
  *)      OS_NAME="$OS";;
esac

PM=""
for m in brew apt-get dnf pacman zypper apk; do
  if have "$m"; then PM="$m"; break; fi
done

# yt-dlp ships as a Python package too, which is often fresher than distro builds.
PIPX=""
for m in pipx pip3 pip; do
  if have "$m"; then PIPX="$m"; break; fi
done

SUDO=""
if [ "$(id -u)" != "0" ] && [ "$PM" != "brew" ] && [ -n "$PM" ]; then
  have sudo && SUDO="sudo "
fi

# ---------------------------------------------------------------- what's there

whisper_cmd() {
  for w in mlx_whisper whisper-ctranslate2 whisper; do
    have "$w" && { echo "$w"; return; }
  done
  echo ""
}

# Pick the fastest engine that fits the hardware. All are free and local; they
# differ only in how well they use the machine.
#   mlx          Apple Silicon, runs on the Metal GPU
#   ctranslate2  CUDA if present, and ~4x faster than the reference on plain CPU
#   openai       the reference implementation, the slowest, works everywhere
pick_engine() {
  [ -n "$ENGINE" ] && { echo "$ENGINE"; return; }
  if [ "$OS_NAME" = "macOS" ] && [ "$(uname -m)" = "arm64" ]; then echo "mlx"; return; fi
  echo "ctranslate2"
}

FFMPEG_OK=0; YTDLP_OK=0
have ffmpeg && FFMPEG_OK=1
have yt-dlp && YTDLP_OK=1
WHISPER="$(whisper_cmd)"

row() { printf '  %-9s %-8s %s\n' "$1" "$2" "$3"; }

echo "watch-video — dependency check"
echo "  platform  $OS_NAME${PM:+ · $PM}"
echo
row ffmpeg  "$([ $FFMPEG_OK -eq 1 ] && echo ok || echo MISSING)" "$([ $FFMPEG_OK -eq 1 ] && ffmpeg -version 2>/dev/null | head -1 | cut -c1-46 || echo 'required — frames and metadata')"
row yt-dlp  "$([ $YTDLP_OK -eq 1 ] && echo ok || echo MISSING)" "$([ $YTDLP_OK -eq 1 ] && yt-dlp --version 2>/dev/null || echo 'required for URLs — 1750+ sites')"
row whisper "$([ -n "$WHISPER" ] && echo ok || echo '-')" "$([ -n "$WHISPER" ] && echo "$WHISPER" || echo "optional, free, local — transcripts when a video has no captions (would install $(pick_engine))")"
echo

MISSING=()
[ $FFMPEG_OK -eq 0 ] && MISSING+=("ffmpeg")
[ $YTDLP_OK -eq 0 ] && MISSING+=("yt-dlp")
[ $WANT_WHISPER -eq 1 ] && [ -z "$WHISPER" ] && MISSING+=("whisper")

if [ ${#MISSING[@]} -eq 0 ]; then
  echo "Everything watch-video needs is installed."
  [ -z "$WHISPER" ] && echo "Tip: --with-whisper adds transcripts for videos that ship no captions."
  [ -z "$WHISPER" ] && echo "     Free and fully local — no API key, no account, nothing sent anywhere."
  exit 0
fi

if [ "$CHECK_ONLY" -eq 1 ]; then
  echo "Missing: ${MISSING[*]}"
  echo "Run without --check to install."
  exit 1
fi

# ---------------------------------------------------------------- build a plan

if [ "$OS_NAME" = "Windows" ]; then
  echo "Missing: ${MISSING[*]}"
  echo
  echo "On Windows, install with one of:"
  echo "  winget install Gyan.FFmpeg  ;  winget install yt-dlp.yt-dlp"
  echo "  choco install ffmpeg yt-dlp"
  echo "  scoop install ffmpeg yt-dlp"
  exit 1
fi

CMDS=(); UNPLANNED=()
for dep in "${MISSING[@]}"; do
  before=${#CMDS[@]}
  case "$dep:$PM" in
    ffmpeg:brew)     CMDS+=("brew install ffmpeg");;
    ffmpeg:apt-get)  CMDS+=("${SUDO}apt-get update" "${SUDO}apt-get install -y ffmpeg");;
    ffmpeg:dnf)      CMDS+=("${SUDO}dnf install -y ffmpeg");;
    ffmpeg:pacman)   CMDS+=("${SUDO}pacman -S --noconfirm ffmpeg");;
    ffmpeg:zypper)   CMDS+=("${SUDO}zypper install -y ffmpeg");;
    ffmpeg:apk)      CMDS+=("${SUDO}apk add ffmpeg");;
    yt-dlp:brew)     CMDS+=("brew install yt-dlp");;
    # Distro yt-dlp packages go stale fast, and a stale yt-dlp is the single most
    # common cause of "this video suddenly stopped downloading". Prefer pipx/pip.
    yt-dlp:*)
      case "$PIPX" in
        pipx)  CMDS+=("pipx install yt-dlp");;
        pip3)  CMDS+=("pip3 install --user --upgrade yt-dlp");;
        pip)   CMDS+=("pip install --user --upgrade yt-dlp");;
        *)     CMDS+=("${SUDO}${PM:-apt-get} install -y yt-dlp");;
      esac;;
    whisper:*)
      case "$(pick_engine)" in
        mlx)          PKG="mlx-whisper";;
        ctranslate2)  PKG="whisper-ctranslate2";;
        openai)       PKG="openai-whisper";;
        *) echo "unknown --whisper-engine: $ENGINE (use mlx, ctranslate2 or openai)" >&2; exit 2;;
      esac
      case "$PIPX" in
        pipx) CMDS+=("pipx install $PKG");;
        *)    CMDS+=("${PIPX:-pip3} install --user --upgrade $PKG");;
      esac;;
  esac
  # No rule matched this dependency on this platform — say so rather than
  # quietly installing a subset and reporting success.
  [ ${#CMDS[@]} -eq "$before" ] && UNPLANNED+=("$dep")
done

echo "Missing: ${MISSING[*]}"
echo

if [ ${#UNPLANNED[@]} -gt 0 ]; then
  echo "No install rule for: ${UNPLANNED[*]}"
  for dep in "${UNPLANNED[@]}"; do
    case "$dep" in
      ffmpeg)  echo "  ffmpeg   https://ffmpeg.org/download.html";;
      yt-dlp)  echo "  yt-dlp   https://github.com/yt-dlp/yt-dlp#installation";;
      whisper) echo "  whisper  https://github.com/openai/whisper#setup";;
    esac
  done
  echo
fi

if [ ${#CMDS[@]} -eq 0 ]; then
  echo "Nothing can be installed automatically here. Install the above manually."
  exit 1
fi

echo "Planned commands:"
for c in "${CMDS[@]}"; do echo "  $c"; done
echo

if [ "$ASSUME_YES" -ne 1 ]; then
  if [ ! -t 0 ]; then
    echo "Not an interactive terminal. Re-run with --yes to install these."
    exit 1
  fi
  printf 'Run them now? [y/N] '
  read -r reply
  case "$reply" in [yY]*) ;; *) echo "Nothing installed."; exit 1;; esac
fi

for c in "${CMDS[@]}"; do
  echo "→ $c"
  # shellcheck disable=SC2086
  eval "$c" || { echo "Failed: $c" >&2; exit 1; }
done

echo
echo "Re-checking…"
exec "${BASH_SOURCE[0]}" --check
