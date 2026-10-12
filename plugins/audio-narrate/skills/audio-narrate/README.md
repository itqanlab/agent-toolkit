# audio-narrate

Turn text into natural English or Arabic narration, for free. One file, or one file per scene for a video.

## Just ask

> *"read this paragraph aloud and save it"*
> *"make an Arabic narration for this script, one file per scene"*
> *"use the female voice and slow it down a little"*
> *"it says our product name wrong, fix it"*
> *"I'm offline, narrate this anyway"*

The agent runs the commands and hands you the audio files. Nothing to pay and no account to make.

## Two engines

| Engine | Needs | Quality |
| :-- | :-- | :-- |
| edge-tts (default) | Internet | Natural neural voices. Clearly the better Arabic |
| Piper | Nothing once set up | Works offline. More robotic |

For a studio voice, a cloned voice or exact timing per character, the paid `elevenlabs-studio` skill is the step up.

## Requirements

- **Python 3** (or `uv`) and **ffmpeg**.
- About **155 MB** for the Python environment, and **126 MB** more if you want the offline voices.

```bash
bash scripts/setup.sh --check    # what is there, what is missing, and how to install it
bash scripts/setup.sh            # the environment with both engines
bash scripts/setup.sh --piper    # also the two offline voices
```

Windows: `.\scripts\setup.ps1` with `-Check` or `-Piper`. Not yet tested on Windows.

Everything is stored outside the skill folder, in `AUDIO_NARRATE_HOME`, or `audio-narrate` inside `AGENT_TOOLKIT_HOME` (by default `~/.itqan-agent-toolkit`). Reinstalling the skill keeps the voices.

## Command line

```bash
bash scripts/run.sh edge --text "Welcome to the tour." --out intro.mp3
bash scripts/run.sh edge --text "مرحبا بكم في الجولة." --female --out intro_ar.mp3
bash scripts/run.sh edge --input script.json --per-segment scenes/ --out scene.mp3
bash scripts/run.sh piper --text "No internet needed." --out offline.wav
```

`script.json`:

```json
[
  { "lang": "ar", "text": "مرحبا بكم." },
  { "lang": "en", "text": "Welcome." },
  { "text": "The language of this line is detected." }
]
```

With `--per-segment scenes/` you get `scenes/001_ar.mp3`, `scenes/002_en.mp3`, `scenes/003_en.mp3`.

## Pronunciation

Put a `narrate-lexicon.json` in your project folder. Each key is respelled before it is spoken:

```json
{ "ar": { "لاب": "لَاابْ" }, "en": { "SQL": "sequel" } }
```

## Calling it from your own scripts

The engines keep the interface of the `voiceover` skill this was ported from. A script that called that skill changes two paths:

| Was | Now |
| :-- | :-- |
| `<skills>/voiceover/.venv/bin/python` | `<AGENT_TOOLKIT_HOME>/audio-narrate/venv/bin/python`, by default `~/.itqan-agent-toolkit/audio-narrate/venv/bin/python`. `bash scripts/setup.sh --where` prints it |
| `<skills>/voiceover/scripts/tts.py` and `edge.py` | `<skills>/audio-narrate/scripts/tts.py` and `edge.py` |
| `<skills>/voiceover/scripts/setup.sh` | `<skills>/audio-narrate/scripts/setup.sh --piper` |

Same flags (`--input`, `--out`, `--per-segment`, `--voice`, `--rate` and the rest), same `[{lang,text}]` input, and the same `NNN_<lang>.<ext>` files per segment.

## Troubleshooting

- **"Microsoft's voice service refused the request"**: the free edge endpoint is unofficial and sometimes blocks the client. Use Piper meanwhile.
- **"path too long for espeak-ng"**: Piper cannot read data from a folder path over about 160 characters. Set `AUDIO_NARRATE_HOME` to a shorter folder and run setup again.

## Install

Claude Code:

```
/plugin marketplace add itqanlab/agent-toolkit
/plugin install audio-narrate@itqan
```

Any other agent:

```bash
./scripts/install.sh audio-narrate
```
