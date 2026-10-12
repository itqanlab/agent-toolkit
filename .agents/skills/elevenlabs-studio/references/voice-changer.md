# Voice changer

API facts for `node scripts/eleven.mjs change`. Adapted from the ElevenLabs agent skills (MIT, see `ATTRIBUTION.md`).

Speech to speech: keep the performance of a recording (its timing, emotion and delivery) and say it in another voice.

## Endpoint

`POST /v1/speech-to-speech/{voice_id}?output_format=...`, `multipart/form-data` with the recording as `audio`. Returns audio.

## Limits

- At most 5 minutes per request. The tool refuses longer input before sending it. Cut it into parts and join the outputs.
- At most 50 MB. Compress to MP3 if the source is larger.

## Flags the tool maps

| Flag | API field | Notes |
| :-- | :-- | :-- |
| `--voice ID` | path | The target voice. Pick it free, from `voices --previews` |
| `--model` | `model_id` | Default `eleven_multilingual_sts_v2` (29 languages). ElevenLabs says it often beats `eleven_english_sts_v2` even on English |
| `--denoise` | `remove_background_noise` | Clean the input first. Noise hurts more here than anywhere else |
| `--settings '{...}'` | `voice_settings` | Override the voice's stored settings for this call |
| `--format` | `output_format` | Default `mp3_44100_128` |

## Cost

1000 credits per minute of input audio. Published in ElevenLabs' own skill guide, not yet measured here. A noisy source is cheaper to fix with `--denoise` in the same call than with a separate `isolate` run.
