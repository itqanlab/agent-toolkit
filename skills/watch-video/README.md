# watch-video

Claude cannot play a video. This gives it the next best thing: a transcript plus an ordered strip of frames it can actually Read.

Point it at a YouTube / Shorts / TikTok / Reels / Vimeo / X URL, or a local file. It downloads the video, pulls whatever captions the platform has, extracts evenly spaced downscaled frames, and prints a manifest of paths. The agent reads those and can then describe the hook, pacing, cuts, on-screen text, aspect ratio, branding — or answer a specific question about the content.

No API key. Nothing leaves your machine except the download itself.

## Install

```
/plugin marketplace add itqanlab/skills
/plugin install watch-video@itqan-skills
```

## Requirements

| Tool | Needed for | Install |
| :-- | :-- | :-- |
| `ffmpeg` | always | `brew install ffmpeg` · `apt install ffmpeg` |
| `yt-dlp` | URLs only | `brew install yt-dlp` · `pipx install yt-dlp` |

## Usage

Just ask — "watch this video and tell me why the hook works", with a URL. The skill triggers on its own.

Directly:

```bash
bash "scripts/watch.sh" <url-or-path> [options]
```

| Option | Default | Meaning |
| :-- | :-- | :-- |
| `--frames N` | 30 (max 60) | Target frame count. More frames = finer detail, more tokens to read |
| `--width W` | 480 | Frame width in px. Raise only to read fine on-screen text |
| `--start SEC` / `--end SEC` | — | Sample only a time range. Use this on long videos |
| `--lang CODE` | `en.*` | Caption language pattern, e.g. `ar.*`, `es.*`, `all` |
| `--outdir DIR` | temp dir | Where frames and transcript land |

## Examples

```bash
# a short — 30 frames covers it at roughly one per 1–2s
watch.sh "https://www.youtube.com/shorts/XXXXXXXX"

# a section of a long video, higher resolution to read slide text
watch.sh "https://youtu.be/XXXXXXXX" --start 420 --end 480 --frames 40 --width 800

# a local file, Arabic captions, keep the output next to the project
watch.sh ./ads/cut-03.mp4 --lang "ar.*" --outdir ./analysis/cut-03
```

## How it works

1. `yt-dlp` fetches the video (capped at 1920px tall) plus auto or uploaded subtitles, converted to `.srt`. Local files skip this step.
2. `ffprobe` reads duration and dimensions; the frame rate is computed so the requested frame count spans the clip, capped at 2 fps.
3. `ffmpeg` extracts and downscales frames to `frame_001.jpg`, `frame_002.jpg`, …
4. A manifest prints the transcript path, frame paths, and source metadata for the agent to read.

## Limits

- Reads publicly accessible videos only. It does not bypass logins, paywalls, or DRM.
- No captions on the source means frames only — still usually enough to describe format and pacing.
- Long videos download in full before framing. Prefer `--start` / `--end`.

## License

MIT
