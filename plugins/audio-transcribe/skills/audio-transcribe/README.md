# audio-transcribe

Turn speech in any audio or video into text, on your own machine, for free.

## Just ask

Once the skill is installed, say what you want in your own words:

> *"transcribe this voice note"*
> *"what does this recording say? it's in Arabic"*
> *"make English subtitles for this video"*
> *"transcribe this YouTube talk"*

The agent runs it and gives you the text. Nothing is uploaded anywhere: Whisper runs on your computer, so it is safe for private recordings.

## Requirements

- **ffmpeg**, to read any audio or video.
- **A local Whisper engine**: `mlx-whisper` on an Apple Silicon Mac, `whisper-ctranslate2` or `openai-whisper` elsewhere. All free and open source.
- **yt-dlp**, only for links to YouTube and other sites.
- **bash**. On Windows, Git Bash or WSL.

The skill checks for these and offers to install what is missing:

```bash
sh scripts/setup-deps.sh --check    # what is there?
sh scripts/setup-deps.sh            # show the install commands, ask, then run them
```

```powershell
.\scripts\setup-deps.ps1 -Check     # Windows
```

The first time a model is used it is downloaded once: about 1.6 GB for the default `turbo`, 3.1 GB for `large`. The script says the size and stops until you allow it with `--allow-download`.

## Command line

```bash
bash scripts/transcribe.sh <source> [options]
```

| Option | Values | Default |
| :-- | :-- | :-- |
| `--lang` | `ar`, `en`, `auto`, or any Whisper language code | `auto` |
| `--model` | `turbo`, `large`, `medium`, `small`, `base` | `turbo` |
| `--format` | `txt`, `srt`, `vtt`, `json` | `txt` |
| `--out DIR` | also write `<source name>.<format>` into DIR | none |
| `--prompt "..."` | names and terms to spell right | none |
| `--engine` | `mlx`, `ctranslate2`, `openai` | the fastest one installed |
| `--allow-download` | allow the first download of a model | off |

`<source>` can be a local file, a direct media link, or a site link:

```bash
bash scripts/transcribe.sh meeting.m4a --lang en
bash scripts/transcribe.sh clip.mp4 --format srt --out captions
bash scripts/transcribe.sh https://example.com/episode.mp3
bash scripts/transcribe.sh "https://www.youtube.com/watch?v=..." --lang ar
```

### For scripts that call it

- The transcript is printed to **stdout**. Notes and warnings go to **stderr**.
- On failure, the last stdout line is `__TRANSCRIBE_FAILED__`, a reason is printed to stderr after `TRANSCRIBE_UNAVAILABLE:`, and the exit code is 1. Bad options exit 2.
- With `--out`, the file is named after the source (`meeting.srt`), not `out.<format>`.

## Example

```
$ bash scripts/transcribe.sh hello.wav --lang en
[transcribe] 4s of audio · lang en · mlx · mlx-community/whisper-large-v3-turbo
Hello world, the Toolkit transcribes speech on this machine for free.
```

## Accuracy

Whisper invents text over silence, can loop on one phrase, and misspells names. The script warns on near-silent audio and retries a loop once with the `large` model. Pass names with `--prompt`. Check any number, date or amount against the audio before acting on it.

## Install

Claude Code:

```
/plugin marketplace add itqanlab/agent-toolkit
/plugin install audio-transcribe@itqan
```

Any other agent:

```bash
./scripts/install.sh audio-transcribe
```
