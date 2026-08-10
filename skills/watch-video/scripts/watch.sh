#!/bin/bash
# watch.sh — download a video (or use a local file), pull captions, extract frames.
# The agent then Reads the frames + transcript to "watch" the video. No API key needed.
#
# Usage: watch.sh <url-or-path> [--frames N] [--width W] [--start SEC] [--end SEC] [--lang CODE] [--outdir DIR]
#   --frames  target number of frames to extract (default 30, capped 60)
#   --width   frame width px (default 480)
#   --start/--end  clip a time range (seconds) before extracting
#   --lang    caption language pattern for yt-dlp (default "en.*"; e.g. "ar.*", "all")
#   --outdir  where to write (default: a fresh temp dir)
set -e

SRC="$1"; shift || true
FRAMES=30; WIDTH=480; START=""; END=""; OUTDIR=""; LANG_PAT="en.*"
while [ $# -gt 0 ]; do
  case "$1" in
    --frames) FRAMES="$2"; shift 2;;
    --width)  WIDTH="$2";  shift 2;;
    --start)  START="$2";  shift 2;;
    --end)    END="$2";    shift 2;;
    --lang)   LANG_PAT="$2"; shift 2;;
    --outdir) OUTDIR="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done
[ -z "$SRC" ] && { echo "usage: watch.sh <url-or-path> [opts]" >&2; exit 2; }
[ "$FRAMES" -gt 60 ] && FRAMES=60
[ -z "$OUTDIR" ] && OUTDIR="$(mktemp -d)/watch"
mkdir -p "$OUTDIR"

command -v ffmpeg >/dev/null || { echo "ffmpeg not installed (brew install ffmpeg / apt install ffmpeg)" >&2; exit 1; }

SRT=""
if printf '%s' "$SRC" | grep -qiE '^https?://'; then
  command -v yt-dlp >/dev/null || { echo "yt-dlp not installed (brew install yt-dlp / pipx install yt-dlp)" >&2; exit 1; }
  yt-dlp -q --no-warnings --write-auto-subs --write-subs --sub-lang "$LANG_PAT" --convert-subs srt \
    -f "bv*[height<=1920]+ba/b" --merge-output-format mp4 \
    -o "$OUTDIR/video.%(ext)s" "$SRC" >&2 || true
  VID="$OUTDIR/video.mp4"
  SRT=$(ls "$OUTDIR"/video*.srt 2>/dev/null | head -1 || true)
  yt-dlp -q --no-warnings --skip-download \
    --print "TITLE: %(title)s|UPLOADER: %(uploader)s|DURATION: %(duration)ss|VIEWS: %(view_count)s|DATE: %(upload_date)s" \
    "$SRC" > "$OUTDIR/meta.txt" 2>/dev/null || true
else
  VID="$SRC"
  [ -f "$VID" ] || { echo "file not found: $VID" >&2; exit 1; }
fi
[ -f "$VID" ] || { echo "no video produced/found" >&2; exit 1; }

DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$VID")
DIM=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 "$VID")
# effective duration for a clipped range
EFF="$DUR"
[ -n "$START" ] && [ -n "$END" ] && EFF=$(awk "BEGIN{print $END-$START}")
FPS=$(awk "BEGIN{d=$EFF; if(d<=0)d=1; f=$FRAMES/d; if(f>2)f=2; print f}")

SS=(); [ -n "$START" ] && SS=(-ss "$START")
TT=(); [ -n "$END" ] && [ -n "$START" ] && TT=(-t "$(awk "BEGIN{print $END-$START}")")
ffmpeg -v error "${SS[@]}" -i "$VID" "${TT[@]}" -vf "fps=$FPS,scale=$WIDTH:-1" "$OUTDIR/frame_%03d.jpg"

echo "=== WATCH MANIFEST ==="
[ -f "$OUTDIR/meta.txt" ] && cat "$OUTDIR/meta.txt"
echo "VIDEO: $VID"
echo "DURATION: ${DUR}s  DIMS: $DIM"
echo "OUTDIR: $OUTDIR"
[ -n "$SRT" ] && echo "TRANSCRIPT (srt): $SRT" || echo "TRANSCRIPT: none (no captions available)"
echo "FRAMES: $(ls "$OUTDIR"/frame_*.jpg 2>/dev/null | wc -l | tr -d ' ')"
ls "$OUTDIR"/frame_*.jpg 2>/dev/null
echo "=== NEXT: Read the TRANSCRIPT (if any) then Read the FRAMES in order to analyze the video. ==="
