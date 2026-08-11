#!/bin/bash
# watch.sh — turn a video into something an agent can read: a transcript plus frames.
#
# Works with any source yt-dlp supports (1750+ sites: YouTube, TikTok, Instagram,
# X, Facebook, Vimeo, Reddit, Twitch, Bilibili, LinkedIn …) or a local file.
#
# Usage: watch.sh <url-or-path> [options]
#   --frames N        target frames to extract (default 30, capped 60)
#   --width W         frame width in px (default 480)
#   --start SEC       clip start
#   --end SEC         clip end
#   --lang CODE       caption language pattern (default "en.*"; e.g. "ar.*", "all")
#   --scenes          sample on scene changes instead of a fixed interval
#   --whisper         transcribe locally when the source ships no captions
#   --cookies BROWSER use browser cookies for login-gated videos (chrome, firefox…)
#   --playlist N      allow a playlist and take the first N entries (default: single)
#   --outdir DIR      where to write (default: a fresh temp dir)
#   --keep-video      do not delete the downloaded video afterwards
set -e

SRC="$1"; shift || true
FRAMES=30; WIDTH=480; START=""; END=""; OUTDIR=""; LANG_PAT="en.*"
SCENES=0; WHISPER=0; COOKIES=""; PLAYLIST=0; KEEP=0

while [ $# -gt 0 ]; do
  case "$1" in
    --frames)   FRAMES="$2"; shift 2;;
    --width)    WIDTH="$2";  shift 2;;
    --start)    START="$2";  shift 2;;
    --end)      END="$2";    shift 2;;
    --lang)     LANG_PAT="$2"; shift 2;;
    --scenes)   SCENES=1; shift;;
    --whisper)  WHISPER=1; shift;;
    --cookies)  COOKIES="$2"; shift 2;;
    --playlist) PLAYLIST="$2"; shift 2;;
    --outdir)   OUTDIR="$2"; shift 2;;
    --keep-video) KEEP=1; shift;;
    -h|--help)  sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

[ -z "$SRC" ] && { echo "usage: watch.sh <url-or-path> [options]" >&2; exit 2; }
[ "$FRAMES" -gt 60 ] && FRAMES=60
[ -z "$OUTDIR" ] && OUTDIR="$(mktemp -d)/watch"
mkdir -p "$OUTDIR"

HERE="$(cd "$(dirname "$0")" && pwd)"
need() {
  command -v "$1" >/dev/null 2>&1 && return 0
  echo "$1 is not installed." >&2
  echo "Run the setup wizard to install what this skill needs:" >&2
  echo "  bash \"$HERE/setup.sh\"" >&2
  exit 1
}
need ffmpeg

SRT=""; IS_URL=0
printf '%s' "$SRC" | grep -qiE '^https?://' && IS_URL=1

if [ "$IS_URL" -eq 1 ]; then
  need yt-dlp

  DL=(yt-dlp -q --no-warnings --write-auto-subs --write-subs
      --sub-lang "$LANG_PAT" --convert-subs srt
      -f "bv*[height<=1920]+ba/b" --merge-output-format mp4)

  # Without this a playlist URL downloads every entry through the same output
  # template, so each one overwrites the last and only the final video survives.
  if [ "$PLAYLIST" = "0" ]; then
    DL+=(--no-playlist)
  else
    DL+=(--yes-playlist --playlist-items "1:${PLAYLIST}"
         -o "$OUTDIR/video_%(playlist_index)s.%(ext)s")
  fi
  [ -n "$COOKIES" ] && DL+=(--cookies-from-browser "$COOKIES")
  [ "$PLAYLIST" = "0" ] && DL+=(-o "$OUTDIR/video.%(ext)s")

  "${DL[@]}" "$SRC" >&2 || {
    echo "yt-dlp could not fetch that source." >&2
    echo "If it needs a login, retry with: --cookies chrome" >&2
    echo "If it worked before, yt-dlp may be out of date — see setup.sh" >&2
    exit 1
  }

  VID="$(ls "$OUTDIR"/video*.mp4 "$OUTDIR"/video*.mkv "$OUTDIR"/video*.webm \
         "$OUTDIR"/video*.m4a "$OUTDIR"/video*.mp3 2>/dev/null | head -1 || true)"
  SRT="$(ls "$OUTDIR"/video*.srt 2>/dev/null | head -1 || true)"
  yt-dlp -q --no-warnings --skip-download --no-playlist \
    --print "TITLE: %(title)s|UPLOADER: %(uploader)s|DURATION: %(duration)ss|VIEWS: %(view_count)s|DATE: %(upload_date)s|SITE: %(extractor_key)s" \
    "$SRC" > "$OUTDIR/meta.txt" 2>/dev/null || true
else
  VID="$SRC"
  [ -f "$VID" ] || { echo "file not found: $VID" >&2; exit 1; }
fi
[ -n "$VID" ] && [ -f "$VID" ] || { echo "no media produced or found" >&2; exit 1; }

DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$VID" 2>/dev/null || echo 0)
DIM=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 "$VID" 2>/dev/null || true)

# Audio-only sources (SoundCloud, podcast feeds, .m4a) have no video stream.
# Extracting frames from one used to fail; now it just returns the transcript.
HAS_VIDEO=1
[ -z "$DIM" ] && HAS_VIDEO=0

# --- transcript fallback ---------------------------------------------------
# Only when the source shipped no captions and the caller opted in, because
# transcribing is much slower than downloading a caption file.
if [ -z "$SRT" ] && [ "$WHISPER" -eq 1 ]; then
  W=""
  for c in mlx_whisper whisper; do command -v "$c" >/dev/null 2>&1 && { W="$c"; break; }; done
  if [ -n "$W" ]; then
    echo "no captions on the source — transcribing locally with $W (this takes a while)" >&2
    "$W" "$VID" --output_dir "$OUTDIR" --output_format srt >/dev/null 2>&1 || true
    SRT="$(ls "$OUTDIR"/*.srt 2>/dev/null | head -1 || true)"
  else
    echo "no captions, and no local whisper installed — run: bash \"$HERE/setup.sh\" --with-whisper" >&2
  fi
fi

# --- frames ----------------------------------------------------------------
FRAME_COUNT=0
if [ "$HAS_VIDEO" -eq 1 ]; then
  EFF="$DUR"
  [ -n "$START" ] && [ -n "$END" ] && EFF=$(awk "BEGIN{print $END-$START}")
  SS=(); [ -n "$START" ] && SS=(-ss "$START")
  TT=(); [ -n "$END" ] && [ -n "$START" ] && TT=(-t "$(awk "BEGIN{print $END-$START}")")

  if [ "$SCENES" -eq 1 ]; then
    # One frame per visual cut. For edited video this beats a fixed interval:
    # you get the shots that exist rather than arbitrary samples across them.
    ffmpeg -v error "${SS[@]}" -i "$VID" "${TT[@]}" \
      -vf "select='gt(scene,0.3)',scale=$WIDTH:-1" -vsync vfr \
      -frames:v "$FRAMES" "$OUTDIR/frame_%03d.jpg" 2>/dev/null || true
  fi

  FRAME_COUNT=$(ls "$OUTDIR"/frame_*.jpg 2>/dev/null | wc -l | tr -d ' ')
  # Fall back to even sampling when scene detection found too little to be useful
  # (static screencasts, single-shot talking heads).
  if [ "$FRAME_COUNT" -lt 3 ]; then
    rm -f "$OUTDIR"/frame_*.jpg
    FPS=$(awk "BEGIN{d=$EFF; if(d<=0)d=1; f=$FRAMES/d; if(f>2)f=2; print f}")
    ffmpeg -v error "${SS[@]}" -i "$VID" "${TT[@]}" \
      -vf "fps=$FPS,scale=$WIDTH:-1" -frames:v "$FRAMES" "$OUTDIR/frame_%03d.jpg"
    FRAME_COUNT=$(ls "$OUTDIR"/frame_*.jpg 2>/dev/null | wc -l | tr -d ' ')
  fi
fi

[ "$IS_URL" -eq 1 ] && [ "$KEEP" -eq 0 ] && [ "$HAS_VIDEO" -eq 1 ] && rm -f "$VID" 2>/dev/null || true

echo "=== WATCH MANIFEST ==="
[ -f "$OUTDIR/meta.txt" ] && cat "$OUTDIR/meta.txt"
echo "SOURCE: $SRC"
echo "DURATION: ${DUR}s${DIM:+  DIMS: $DIM}"
[ "$HAS_VIDEO" -eq 0 ] && echo "NOTE: audio-only source — transcript only, no frames"
echo "OUTDIR: $OUTDIR"
if [ -n "$SRT" ]; then echo "TRANSCRIPT (srt): $SRT"; else
  echo "TRANSCRIPT: none (source has no captions; add --whisper to transcribe locally)"; fi
SAMPLING=""; [ "$SCENES" -eq 1 ] && [ "$FRAME_COUNT" -gt 0 ] && SAMPLING=" (scene-sampled)"
echo "FRAMES: ${FRAME_COUNT}${SAMPLING}"
ls "$OUTDIR"/frame_*.jpg 2>/dev/null || true
echo "=== NEXT: Read the TRANSCRIPT (if any) then Read the FRAMES in order to analyze the video. ==="
