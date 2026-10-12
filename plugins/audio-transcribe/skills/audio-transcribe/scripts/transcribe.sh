#!/usr/bin/env bash
# transcribe.sh — speech to text for any audio or video source, fully local.
#
# Usage:
#   scripts/transcribe.sh <source> [--lang ar|en|auto|<code>] [--model turbo|large|medium|small|base|org/repo]
#                         [--format txt|srt|vtt|json] [--out DIR] [--prompt "..."]
#                         [--engine mlx|ctranslate2|openai] [--allow-download]
#
# <source> is one of:
#   path/to/file.(ogg|mp3|m4a|wav|mp4|mov|...)   local audio or video
#   https://.../file.mp3                         direct media URL
#   https://youtube.com/... (any yt-dlp site)    fetched with yt-dlp
#
# The transcript goes to stdout, notes to stderr. With --out, the file is also
# written to DIR as <source name>.<format>. On failure the last stdout line is
# __TRANSCRIBE_FAILED__ and the exit code is non-zero, so a caller in a loop can
# carry on without it.
#
# Engines, all free and local (nothing leaves the machine):
#   mlx          mlx_whisper, Apple Silicon GPU. The fastest on a Mac.
#   ctranslate2  whisper-ctranslate2. About 4x the reference speed on a CPU, CUDA when present.
#   openai       whisper, the reference implementation. The slowest, works everywhere.
# The first one installed wins, in that order, unless --engine picks one.
#
# A model that is not on disk yet is never downloaded silently: the script says how
# big it is and stops, unless --allow-download is given.
set -euo pipefail

SRC="${1:-}"
if [ -z "$SRC" ] || [ "$SRC" = "-h" ] || [ "$SRC" = "--help" ]; then
  sed -n '2,26p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 2
fi
shift

LANG_CODE="auto"; MODEL="turbo"; FORMAT="txt"; OUTDIR=""; PROMPT=""; ENGINE=""; ALLOW_DL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --lang)   LANG_CODE="${2:?--lang needs a value}"; shift 2 ;;
    --model)  MODEL="${2:?--model needs a value}";     shift 2 ;;
    --format) FORMAT="${2:?--format needs a value}";   shift 2 ;;
    --out)    OUTDIR="${2:?--out needs a directory}";  shift 2 ;;
    --prompt) PROMPT="${2:?--prompt needs text}";      shift 2 ;;
    --engine) ENGINE="${2:?--engine needs a value}";   shift 2 ;;
    --allow-download) ALLOW_DL=1; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

note() { echo "[transcribe] $*" >&2; }
fail() { echo "TRANSCRIBE_UNAVAILABLE: $1" >&2; echo "__TRANSCRIBE_FAILED__"; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

case "$FORMAT" in txt|srt|vtt|json) ;; *) fail "--format must be txt, srt, vtt or json" ;; esac
have ffmpeg  || fail "ffmpeg is not installed. Run: sh scripts/setup-deps.sh"
have ffprobe || fail "ffprobe is not installed (it comes with ffmpeg). Run: sh scripts/setup-deps.sh"

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
MEDIA=""; NAME="transcript"

# ---------------------------------------------------------------- 1. source to a local file
case "$SRC" in
  http://*|https://*)
    if [[ "$SRC" =~ \.(mp3|m4a|wav|ogg|opus|oga|flac|aac|mp4|mov|webm|mkv)(\?|$) ]]; then
      EXT="${BASH_REMATCH[0]%%\?*}"
      MEDIA="$WORK/media$EXT"
      HTTP="$(curl -sL -o "$MEDIA" -w '%{http_code}' "$SRC")" || true
      [ "$HTTP" = "200" ] || fail "download failed (HTTP $HTTP)"
      NAME="$(basename "${SRC%%\?*}")"; NAME="${NAME%.*}"
    else
      have yt-dlp || fail "yt-dlp is needed for this link. Run: sh scripts/setup-deps.sh"
      note "not a direct media link, fetching the audio with yt-dlp"
      yt-dlp -q --no-warnings -f 'bestaudio/best' -x --audio-format mp3 \
        -o "$WORK/media.%(ext)s" "$SRC" >&2 || fail "yt-dlp could not fetch the audio"
      MEDIA="$(find "$WORK" -maxdepth 1 -name 'media.*' | head -1)"
      NAME="$(yt-dlp --no-warnings --get-id "$SRC" 2>/dev/null | head -1 || true)"; NAME="${NAME:-transcript}"
    fi
    ;;
  *)
    [ -f "$SRC" ] || fail "file not found: $SRC"
    MEDIA="$SRC"
    NAME="$(basename "$SRC")"; NAME="${NAME%.*}"
    ;;
esac
[ -s "$MEDIA" ] || fail "the media is empty"

# ---------------------------------------------------------------- 2. 16 kHz mono WAV (drops video)
WAV="$WORK/audio.wav"
ffmpeg -nostdin -v error -y -i "$MEDIA" -vn -ac 1 -ar 16000 -c:a pcm_s16le "$WAV" 2>/dev/null \
  || fail "ffmpeg could not decode the media"
[ -s "$WAV" ] || fail "the source has no audio track"

DUR="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$WAV" 2>/dev/null | cut -d. -f1)"
DUR="${DUR:-0}"

# Whisper invents confident sentences over near-silence. Warn so nobody quotes it.
# volumedetect reports at info level, so -v error would hide it and the guard would never fire.
MEANVOL="$(ffmpeg -nostdin -hide_banner -i "$WAV" -af volumedetect -f null - 2>&1 \
  | awk -F': ' '/mean_volume/{print $2}' | tr -d ' dB')"
if [ -n "$MEANVOL" ] && awk "BEGIN{exit !($MEANVOL < -50)}"; then
  note "WARNING: the audio is near-silent (mean volume ${MEANVOL} dB). Any text is likely invented."
fi

# ---------------------------------------------------------------- 3. engine and model
if [ -z "$ENGINE" ]; then
  if have mlx_whisper; then ENGINE=mlx
  elif have whisper-ctranslate2; then ENGINE=ctranslate2
  elif have whisper; then ENGINE=openai
  else fail "no local Whisper engine is installed. Run: sh scripts/setup-deps.sh --with-whisper"
  fi
fi
case "$ENGINE" in
  mlx)         have mlx_whisper         || fail "mlx_whisper is not installed (pip install mlx-whisper)" ;;
  ctranslate2) have whisper-ctranslate2 || fail "whisper-ctranslate2 is not installed (pip install whisper-ctranslate2)" ;;
  openai)      have whisper             || fail "whisper is not installed (pip install openai-whisper)" ;;
  *) fail "--engine must be mlx, ctranslate2 or openai" ;;
esac

HF_HUB="${HF_HOME:-$HOME/.cache/huggingface}/hub"

# Model id per engine, plus its approximate download size. Sizes are the published
# file sizes, rounded; the first use downloads that much once.
resolve_model() {
  local m="$1"
  case "$ENGINE:$m" in
    mlx:turbo)  ID="mlx-community/whisper-large-v3-turbo"; SIZE="1.6 GB" ;;
    mlx:large)  ID="mlx-community/whisper-large-v3-mlx";   SIZE="3.1 GB" ;;
    mlx:medium) ID="mlx-community/whisper-medium-mlx";     SIZE="1.5 GB" ;;
    mlx:small)  ID="mlx-community/whisper-small-mlx";      SIZE="0.5 GB" ;;
    mlx:base)   ID="mlx-community/whisper-base-mlx";       SIZE="0.15 GB" ;;
    mlx:*/*)    ID="$m"; SIZE="unknown" ;;
    *:turbo)    ID="large-v3-turbo"; SIZE="1.6 GB" ;;
    *:large)    ID="large-v3";       SIZE="3.1 GB" ;;
    *:medium)   ID="medium";         SIZE="1.5 GB" ;;
    *:small)    ID="small";          SIZE="0.5 GB" ;;
    *:base)     ID="base";           SIZE="0.15 GB" ;;
    *) fail "unknown model: $m (use turbo, large, medium, small or base)" ;;
  esac
}

model_cached() {
  case "$ENGINE" in
    mlx)         [ -d "$HF_HUB/models--${ID//\//--}" ] ;;
    ctranslate2) compgen -G "$HF_HUB/models--*faster-whisper-${ID}" >/dev/null ;;
    openai)      [ -f "${XDG_CACHE_HOME:-$HOME/.cache}/whisper/${ID}.pt" ] ;;
  esac
}

run_engine() {
  local model="$1"
  resolve_model "$model"
  if ! model_cached; then
    if [ "$ALLOW_DL" -ne 1 ]; then
      note "the $model model is not on this machine yet. First use downloads about $SIZE, once."
      fail "re-run with --allow-download to download it, or pick a smaller --model"
    fi
    note "downloading the $model model (about $SIZE), once"
  fi

  local lang=(); [ "$LANG_CODE" != "auto" ] && lang=(--language "$LANG_CODE")
  rm -f "$WORK"/out.* "$WORK"/audio.{txt,srt,vtt,json}
  note "${DUR}s of audio · lang $LANG_CODE · $ENGINE · $ID"
  case "$ENGINE" in
    mlx)
      local p=(); [ -n "$PROMPT" ] && p=(--initial-prompt "$PROMPT")
      # Conditioning on previous text is off: it is what feeds Whisper's repetition loops.
      mlx_whisper "$WAV" --model "$ID" ${lang[@]+"${lang[@]}"} ${p[@]+"${p[@]}"} \
        --condition-on-previous-text False \
        --output-format "$FORMAT" --output-dir "$WORK" --output-name out --verbose False >&2 \
        || fail "mlx_whisper failed"
      ;;
    ctranslate2|openai)
      local bin=whisper; [ "$ENGINE" = ctranslate2 ] && bin=whisper-ctranslate2
      local p=(); [ -n "$PROMPT" ] && p=(--initial_prompt "$PROMPT")
      local extra=(); [ "$ENGINE" = openai ] && extra=(--fp16 False)
      "$bin" "$WAV" --model "$ID" ${lang[@]+"${lang[@]}"} ${p[@]+"${p[@]}"} \
        --condition_on_previous_text False ${extra[@]+"${extra[@]}"} \
        --output_format "$FORMAT" --output_dir "$WORK" >/dev/null 2>&1 \
        || fail "$bin failed"
      [ -f "$WORK/audio.$FORMAT" ] && mv "$WORK/audio.$FORMAT" "$WORK/out.$FORMAT"
      ;;
  esac
  [ -s "$WORK/out.$FORMAT" ] || fail "the transcription came back empty"
}

# A decode loop prints one character or phrase over and over.
looped() {
  have python3 || return 1
  python3 - "$1" <<'PY'
import re, sys
t = open(sys.argv[1], encoding="utf-8", errors="replace").read()
loop = re.search(r'(.)\1{14,}', t) or re.search(r'(\b\w[\w\s]{1,20}?\b)(?:\s*\1){5,}', t)
sys.exit(0 if loop else 1)
PY
}

# ---------------------------------------------------------------- 4. transcribe
run_engine "$MODEL"
RESULT="$WORK/out.$FORMAT"

# The full large model escapes loops that turbo gets stuck in. Retry once, on the same audio.
if looped "$RESULT"; then
  if [ "$MODEL" != "large" ]; then
    note "repetition loop on '$MODEL', retrying once with 'large'"
    run_engine large
  fi
  if looped "$RESULT"; then note "WARNING: the text still looks like a repetition loop. Treat it as unreliable."; fi
fi

if [ -n "$OUTDIR" ]; then
  mkdir -p "$OUTDIR"
  cp "$RESULT" "$OUTDIR/$NAME.$FORMAT"
  note "wrote $OUTDIR/$NAME.$FORMAT"
fi

cat "$RESULT"
