# Sound effects

API facts for `node scripts/eleven.mjs sfx`. Parameter table adapted from the ElevenLabs agent skills (MIT, see `ATTRIBUTION.md`).

## Endpoint

`POST /v1/sound-generation?output_format=...` returns audio. The tool always sends `model_id: eleven_text_to_sound_v2`.

| Field | Flag | Range | Default | Effect |
| :-- | :-- | :-- | :-- | :-- |
| `text` | `--text` | required | | What the sound is |
| `duration_seconds` | `--duration` | 0.5 to 30 | chosen by the model | Exact length. Ask for the length the moment needs |
| `prompt_influence` | `--influence` | 0 to 1 | 0.3 | How literally the prompt is followed. Higher is more literal |
| `loop` | `--loop` | | off | A loop with no audible join, for beds and ambience |

Cost: with `--duration` set, about 11.2 credits per second (measured: 2.6 s cost 29 credits, three times). Without it, the published figure is about 200 per generation. So always set the duration. The tool estimates the same way.

## Writing the prompt

- Be specific. "Heavy rain on a tin roof" beats "rain".
- Combine elements. "Footsteps on gravel, distant traffic".
- Name the style. "Cinematic low boom", "soft UI confirmation tick", "8-bit jump".
- Say the mood or what the moment means, not a library name.

One prompt, one take. Listen before making a second. A variation is a new request and costs again; the same request is a cache hit and costs nothing.

## Output formats

`mp3_44100_128` (default), `mp3_44100_192`, `pcm_44100`, `opus_48000_128`, `ulaw_8000`, and the other sample rates and bitrates of each family.
