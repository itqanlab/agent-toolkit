# Speech to text

API facts for `node scripts/eleven.mjs stt`. Parameter tables adapted from the ElevenLabs agent skills (MIT, see `ATTRIBUTION.md`).

## When to use it

A free local transcriber, when the machine has one, costs nothing. Use ElevenLabs when you need what it does better: speaker labels, a list of names it must spell right (`--keyterms`), 90+ languages, or a machine with no local model.

## Endpoint

`POST /v1/speech-to-text`, `multipart/form-data`. Send either `file` (up to 5 GB, 10 hours) or `source_url` (hosted media, including YouTube and TikTok links). The answer is JSON.

The tool writes the plain text to `--out` and the full answer beside it as `<out>.json`: every word with its start and end time, its speaker, and the detected language.

## Models

| Model id | Use it for |
| :-- | :-- |
| `scribe_v2` | The default. Batch transcription, subtitles, long recordings |
| `scribe_v2_medical` | Clinical and medical audio |

The realtime models (`scribe_v2_realtime` and its variants) stream over a WebSocket. This tool does not use them.

## Flags the tool maps

| Flag | API field | Notes |
| :-- | :-- | :-- |
| `--lang en` | `language_code` | A hint. Leave it out to auto-detect |
| `--diarize` | `diarize` | Label who speaks, up to 32 speakers |
| `--speakers N` | `num_speakers` | The most speakers to look for |
| `--keyterms "A,B"` | `keyterms` | Up to 100 terms, each at most 50 characters and 5 words |
| `--clean` | `no_verbatim` | Drop fillers, false starts and non-speech sounds |
| `--no-events` | `tag_audio_events=false` | Do not tag laughter, applause and the like |
| `--model` | `model_id` | `scribe_v2` unless you say otherwise |

Word timestamps are always on.

## Cost

Estimated at 330 credits per minute of audio. That figure comes from third-party pricing write-ups, not ElevenLabs, so it is assumed until the ledger measures it. A URL source has no file to measure, so it needs `--seconds N`.
