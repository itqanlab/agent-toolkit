---
name: watch-video
description: "Watch / analyze a video the agent cannot natively play — a YouTube/TikTok/etc URL or a local video file. Downloads it (yt-dlp), pulls captions, and extracts frames (ffmpeg) so the agent can Read the transcript + frames and describe pacing, hooks, on-screen text, format, or answer questions about the content. No API key needed. Triggers: 'watch this video', 'analyze this short/reel/clip', 'what happens in this video', 'reverse-engineer this video', 'read the frames of', '/watch-video'."
license: MIT
compatibility: Requires ffmpeg, and yt-dlp for URL sources. Needs network access to download remote videos.
metadata:
  author: itqanlab
  version: "1.0.0"
---

# watch-video

Let the agent "watch" a video by turning it into a transcript + frames it can Read.

## When to use
- User shares a video URL (YouTube, Shorts, TikTok, Reels, Vimeo, X, etc.) or a local file and wants it watched, analyzed, summarized, or reverse-engineered (hook, pacing, on-screen text, editing style, format).
- You need to inspect the visual content of a video, not just its metadata.

## Requirements
- `ffmpeg` — required. macOS: `brew install ffmpeg`. Debian/Ubuntu: `apt install ffmpeg`.
- `yt-dlp` — required only for URLs (local files skip it). `brew install yt-dlp` / `pipx install yt-dlp`.
- No API keys. Captions come from the platform's own subtitles (auto or uploaded); if none exist, you get frames only.

## How to use
1. Run the bundled script `scripts/watch.sh` (path is relative to this skill's directory). It prints a manifest with the transcript path + frame paths:
   ```
   bash scripts/watch.sh "<url-or-path>" [--frames N] [--width W] [--start SEC] [--end SEC] [--lang CODE] [--outdir DIR]
   ```
   - `--frames` target frame count (default 30, cap 60). More frames = finer temporal detail, more tokens to Read.
   - `--start/--end` to focus on a time range (seconds).
   - `--lang` caption language pattern (default `en.*`; e.g. `ar.*`, `es.*`, or `all`).
2. **Read the transcript** (the `.srt` path in the manifest), if present.
3. **Read the frames** in order (`frame_001.jpg`, `frame_002.jpg`, …) — the visual track.
4. Synthesize: answer the user's question, or describe hook (first ~1s), pacing/cuts, on-screen text/subtitles, format (letterbox vs full-bleed), branding, and anything notable.

`scripts/watch.sh` sits next to this `SKILL.md`. If the working directory is elsewhere, use the absolute path of this skill's directory — the script has no dependency on where it is invoked from.

## Tips
- Shorts/Reels (<60s): 30 frames ≈ ~1 frame every 1–2s — plenty. Long videos: raise `--frames` or use `--start/--end` to sample a section.
- To compare several videos (e.g. "what makes the top performers work"), run once per URL and read across the frame sets.
- Frames are downscaled (default 480px wide) to stay token-cheap; raise `--width` only if you must read fine text in-frame.
- Output lands in a temp dir by default; pass `--outdir` to keep it alongside project files.

## Notes
- This reads publicly accessible videos. It does not bypass logins, paywalls, or DRM.
- Large/long videos download fully before framing; prefer `--start/--end` for long sources.
