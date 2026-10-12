#!/usr/bin/env bash
# setup.sh — prepare audio-narrate on macOS or Linux. Safe to run again: it only does what is missing.
#
#   bash scripts/setup.sh --check    report what is there and what is missing, change nothing
#   bash scripts/setup.sh            create the Python environment with edge-tts and Piper (about 155 MB)
#   bash scripts/setup.sh --piper    also download the two offline Piper voices (about 126 MB)
#   bash scripts/setup.sh --where    print the Python this skill runs with
#
# Everything goes in one folder outside the skill: AUDIO_NARRATE_HOME, or
# <AGENT_TOOLKIT_HOME>/audio-narrate, with AGENT_TOOLKIT_HOME defaulting to ~/.itqan-agent-toolkit.
set -euo pipefail

ROOT="${AGENT_TOOLKIT_HOME:-$HOME/.itqan-agent-toolkit}"
HOME_DIR="${AUDIO_NARRATE_HOME:-$ROOT/audio-narrate}"
VENV="$HOME_DIR/venv"
VOICES="$HOME_DIR/voices"
PY="$VENV/bin/python"
# piper-tts is pinned: 1.8.0 looks for its espeak data at a path from its own build machine
# and fails on macOS; 1.4.2 works. Raise the pin only after narrating a line with the new one.
PKGS=(edge-tts "piper-tts==1.4.2" numpy)
VOICE_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main"
VOICE_FILES="en/en_US/amy/medium/en_US-amy-medium.onnx ar/ar_JO/kareem/medium/ar_JO-kareem-medium.onnx"

MODE="install"
for a in "$@"; do
  case "$a" in
    --check) MODE="check";;
    --where) MODE="where";;
    --piper) MODE="piper";;
    -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
    *) echo "unknown option: $a" >&2; exit 2;;
  esac
done

if [ "$MODE" = "where" ]; then echo "$PY"; exit 0; fi

size() { stat -f%z "$1" 2>/dev/null || stat -c%s "$1" 2>/dev/null || echo 0; }
voices_ok() {
  for v in $VOICE_FILES; do
    f="$VOICES/$(basename "$v")"
    [ -f "$f" ] && [ "$(size "$f")" -gt 40000000 ] && [ -f "$f.json" ] || return 1
  done
}

if [ "$MODE" = "check" ]; then
  missing=0
  if command -v ffmpeg >/dev/null 2>&1; then echo "ok       ffmpeg"; else
    echo "MISSING  ffmpeg   macOS: brew install ffmpeg   Debian/Ubuntu: sudo apt install ffmpeg"; missing=1; fi
  if command -v uv >/dev/null 2>&1 || command -v python3 >/dev/null 2>&1; then echo "ok       python3 or uv"; else
    echo "MISSING  python3  macOS: brew install python   Debian/Ubuntu: sudo apt install python3 python3-venv"; missing=1; fi
  if [ -x "$PY" ] && "$PY" -c "import edge_tts, piper, numpy" 2>/dev/null; then echo "ok       engines in $VENV"; else
    echo "MISSING  engines  run: bash scripts/setup.sh"; missing=1; fi
  if voices_ok; then echo "ok       Piper voices in $VOICES"; else
    echo "optional Piper voices not downloaded (offline only, about 126 MB): bash scripts/setup.sh --piper"; fi
  exit "$missing"
fi

command -v ffmpeg >/dev/null 2>&1 || echo "note: ffmpeg is missing. Install it before narrating (macOS: brew install ffmpeg, Debian/Ubuntu: sudo apt install ffmpeg)."
mkdir -p "$HOME_DIR"

if [ ! -x "$PY" ]; then
  echo "creating the Python environment in $VENV (edge-tts and Piper, about 155 MB)"
  if command -v uv >/dev/null 2>&1; then
    uv venv --quiet "$VENV" --python 3.12
    uv pip install --quiet --python "$PY" "${PKGS[@]}"
  elif command -v python3 >/dev/null 2>&1; then
    python3 -m venv "$VENV"
    "$PY" -m pip install -q --upgrade pip
    "$PY" -m pip install -q "${PKGS[@]}"
  else
    echo "Python 3 is needed. macOS: brew install python   Debian/Ubuntu: sudo apt install python3 python3-venv" >&2
    exit 1
  fi
fi
if ! "$PY" -c "import edge_tts, piper, numpy; from importlib.metadata import version; assert version('piper-tts') == '1.4.2'" 2>/dev/null; then
  echo "installing the engines into $VENV"
  if command -v uv >/dev/null 2>&1; then uv pip install --quiet --python "$PY" "${PKGS[@]}"; else "$PY" -m pip install -q "${PKGS[@]}"; fi
fi

if [ "$MODE" = "piper" ]; then
  mkdir -p "$VOICES"
  if voices_ok; then echo "Piper voices already present"; else
    echo "downloading two Piper voices, about 126 MB, into $VOICES"
    for v in $VOICE_FILES; do
      f="$VOICES/$(basename "$v")"
      if [ ! -f "$f" ] || [ "$(size "$f")" -lt 40000000 ]; then curl -fsSL -C - --retry 8 -o "$f" "$VOICE_BASE/$v"; fi
      [ -f "$f.json" ] || curl -fsSL --retry 8 -o "$f.json" "$VOICE_BASE/$v.json"
    done
  fi
fi

echo "ready. python: $PY"
