# Dubbing

API facts for `node scripts/eleven.mjs dub`. Adapted from the ElevenLabs agent skills (MIT, see `ATTRIBUTION.md`).

Translates the speech in a video or audio file into another language, in voices cloned from the original speakers.

## How the tool runs it

It uses the Dubbing Projects API, which ElevenLabs now recommends. The older bare `/v1/dubbing` routes are legacy.

1. `POST /v1/dubbing/project` with the `file` (up to 3 GiB) or a `source_url`, `model_id=dubbing_v2`, and `source_language` when given (`--from`). Left out, the language is detected.
2. `POST /v1/dubbing/project/{project_id}/language` with `target_language` (`--to`), and `voice_settings.cloning_strength` when `--cloning` is given (0 to 10, default 7).
3. Polls the language every 10 seconds until it is `completed` or `failed`.
4. Downloads `outputs.lossless_audio`, a WAV. Its link is signed and expires in about an hour.

The output is the dubbed audio track, not a new video. Put it under the picture with any editor or with ffmpeg.

A dub takes minutes. The project and language ids are saved as soon as they exist (`<cache>/<id>.pending.json`), so running the same command again resumes the same job and never pays twice.

## Flags

| Flag | Notes |
| :-- | :-- |
| `--to es` | Target language, ISO 639 code. Required |
| `--from en` | Source language. Optional |
| `--keyterms "Brand,Name"` | Names the transcription and translation must keep. Up to 1000, each at most 50 characters and 5 words, no `<>{}[]\` |
| `--cloning 0-10` | How strongly the dubbed voices copy the originals |
| `--source-url URL --seconds N` | Dub from a link. The length is needed for the price |

## Statuses

Project: `queued`, `preparing`, `ready`, `failed`. A project stays `ready`; progress lives on each language.

Language: `queued`, `processing`, `completed`, `stale` (the transcript changed after it was made), `failed`.

## Editing the transcript

ElevenLabs lets you fix the source transcript or a translation segment and regenerate one language. This tool does not wrap that yet. The routes are under `/v1/dubbing/project/{project_id}/transcript` and `/language/{language_id}/transcript`.

## Cost

Reported anywhere from 2000 to 10000 credits per minute depending on the source and the plan. The tool assumes 10000 a minute so it never under-prices a dub. That is the most expensive call in this skill: always `--dry` first and ask the user before a dub over a minute.
