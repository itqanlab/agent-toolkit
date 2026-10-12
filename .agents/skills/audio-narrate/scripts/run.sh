#!/usr/bin/env bash
# run.sh — run an engine with the skill's own Python, wherever setup put it.
#   bash scripts/run.sh edge  --text "..." --out a.mp3
#   bash scripts/run.sh piper --text "..." --out a.wav
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="${AUDIO_NARRATE_HOME:-${AGENT_TOOLKIT_HOME:-$HOME/.itqan-agent-toolkit}/audio-narrate}/venv/bin/python"
[ -x "$PY" ] || { echo "audio-narrate is not set up yet. Run: bash scripts/setup.sh" >&2; exit 2; }
engine="${1:-}"; shift || true
case "$engine" in
  edge) exec "$PY" "$DIR/edge.py" "$@";;
  piper) exec "$PY" "$DIR/tts.py" "$@";;
  *) echo "usage: run.sh edge|piper [options]   (edge: online, best quality. piper: offline)" >&2; exit 2;;
esac
