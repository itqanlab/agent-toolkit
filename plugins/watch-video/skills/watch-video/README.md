# watch-video

An agent cannot play a video. This gives it the next best thing: a transcript plus an ordered strip of frames it can actually read.

Point it at a URL from **1750+ sites** — YouTube, TikTok, Instagram, X, Facebook, Vimeo, Reddit, Twitch, Dailymotion, Bilibili, SoundCloud, LinkedIn — or a direct media URL, or a local file. It downloads the media, pulls whatever captions exist (or transcribes locally when there are none), extracts evenly spaced or scene-aligned frames, and prints a manifest of paths. The agent reads those and can then describe the hook, pacing, cuts, on-screen text, aspect ratio, branding — or answer a specific question about the content.

No API key. Nothing leaves your machine except the download itself.

## Install

```
/plugin marketplace add itqanlab/agent-toolkit
/plugin install watch-video@itqan
```

Or for any conformant agent, from the toolkit root: `./scripts/install.sh watch-video`

## Setup

```bash
bash scripts/setup.sh --check          # what's installed, what's missing
bash scripts/setup.sh                  # shows a plan, asks, installs
bash scripts/setup.sh --yes            # non-interactive
bash scripts/setup.sh --with-whisper   # add free offline speech-to-text
```

Detects your platform and package manager — Homebrew, apt, dnf, pacman, zypper, apk, pipx/pip — and prints every command before it runs. Nothing is installed without a confirmation or an explicit `--yes`, and anything needing root is shown in full first.

| Tool | Needed for | Notes |
| :-- | :-- | :-- |
| `ffmpeg` | always | Frames and media metadata |
| `yt-dlp` | URLs only | Installed via pip where distro packages go stale |
| a whisper engine | optional | Free and local. Used automatically when a source has no captions. `setup.sh` picks mlx-whisper on Apple Silicon, whisper-ctranslate2 elsewhere |

## Usage

Just ask — *"watch this video and tell me why the hook works"*, with a URL. The skill triggers on its own.

Directly:

```bash
bash scripts/watch.sh <url-or-path> [options]
```

| Option | Default | Meaning |
| :-- | :-- | :-- |
| `--frames N` | 30 (max 60) | Target frame count |
| `--width W` | 480 | Frame width in px |
| `--start SEC` / `--end SEC` | — | Sample a time range only |
| `--lang CODE` | `en.*` | Caption language, e.g. `ar.*`, `all` |
| `--scenes` | off | One frame per visual cut |
| `--no-whisper` | off | Skip local transcription even if an engine is installed |
| `--whisper-model M` | `base` | Speed vs accuracy, e.g. `large-v3` |
| `--yes` | off | Accept prompts, including installing a transcriber |
| `--cookies BROWSER` | — | Login-gated videos, e.g. `chrome` |
| `--playlist N` | single | Allow a playlist, take first N |
| `--outdir DIR` | temp | Where output lands |
| `--keep-video` | off | Keep the download |

## Examples

```bash
# a short — 30 frames covers it at roughly one per 1–2s
watch.sh "https://www.youtube.com/shorts/XXXXXXXX"

# a TikTok, sampled on its cuts rather than on a timer
watch.sh "https://www.tiktok.com/@someone/video/123" --scenes

# a section of a long talk, higher resolution to read slide text
watch.sh "https://youtu.be/XXXXXXXX" --start 420 --end 480 --frames 40 --width 800

# a podcast episode: audio only, so transcript and no frames
watch.sh "https://soundcloud.com/x/y"

# an Arabic video with no captions — transcribed locally, higher accuracy
watch.sh ./ads/cut-03.mp4 --lang "ar.*" --whisper-model large-v3 --outdir ./analysis/cut-03
```

## How it works

1. `yt-dlp` fetches the media (capped at 1920px tall) plus auto or uploaded subtitles, converted to `.srt`. Local files skip this step. Playlists are refused unless `--playlist N` is given, so one URL means one video.
2. `ffprobe` reads duration and dimensions. A source with no video stream is handled as audio-only: transcript, no frames.
3. If the requested language has no captions, it retries for captions in any language. If there are still none, an installed whisper engine transcribes locally — free and offline, no API key.
4. `ffmpeg` extracts frames, either at an even interval or on scene changes with `--scenes`. Scene mode falls back to even sampling when a source has too few cuts to be useful.
5. A manifest prints the transcript path, frame paths and source metadata for the agent to read.

## Limits

- Reads publicly accessible media. It does not bypass paywalls or DRM. `--cookies` reuses a session you are already signed into; it does not defeat access control.
- Long videos download in full before framing. Prefer `--start` / `--end`.
- Local transcription is accurate but much slower than downloading a caption file, so captions are always tried first. `--no-whisper` skips it entirely.
- If a source that used to work stops downloading, yt-dlp is usually out of date — `setup.sh` updates it.

## License

MIT
