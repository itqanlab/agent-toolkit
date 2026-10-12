# Voice isolator

API facts for `node scripts/eleven.mjs isolate`. Adapted from the ElevenLabs agent skills (MIT, see `ATTRIBUTION.md`).

Keeps the voice and removes background noise, music and room sound. Use it to rescue a noisy recording, to clean audio before transcription, or to pull dialogue out of a mixed track.

## Endpoint

`POST /v1/audio-isolation`, `multipart/form-data` with the recording as `audio`. Returns MP3.

## Cost

Estimated at 1000 credits per minute of audio. That figure comes from third-party write-ups, not ElevenLabs, so it is assumed until the ledger measures it.

Before paying for it, ask whether the next step needs it. The voice changer has its own `--denoise`, and transcription copes with moderate noise.
