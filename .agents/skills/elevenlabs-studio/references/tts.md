# Text to speech

API facts for `node scripts/eleven.mjs tts`. Tables adapted from the ElevenLabs agent skills (MIT, see `ATTRIBUTION.md`). ElevenLabs changes models often; when a model id is rejected, list the current ones in the ElevenLabs docs.

## Endpoint

`POST /v1/text-to-speech/{voice_id}?output_format=...` returns audio.
`POST /v1/text-to-speech/{voice_id}/with-timestamps?output_format=...` returns JSON with `audio_base64`, `alignment` and `normalized_alignment` (per-character start and end times). `--timestamps` uses the second one and writes the timing to `<out>.json`.

Body fields the tool sends: `text`, `model_id`, and when given `voice_settings` (`--settings`), `previous_text` (`--prev`), `next_text` (`--next`), `language_code` (`--lang`).

## Models

| Model id | Languages | Use it for | Estimate |
| :-- | :-- | :-- | :-- |
| `eleven_v4` | 90+ | The default here, and ElevenLabs' own default. Highest quality, audio tags such as `[whispers]` and `[laughs]` | ~0.11 per character (measured once: 6 for 53). The tool estimates 0.15 |
| `eleven_v3` | 70+ | Previous expressive model. No stitching, and can drift pitch | ~0.45 per character (measured) |
| `eleven_multilingual_v2` | 29 | Long-form, stable. Supports stitching | ~0.45 per character (measured) |
| `eleven_flash_v2_5` | 32 | Scratch takes and timing checks. Lowest latency | ~0.25 per character (assumed) |
| `eleven_flash_v2` | English only | Fast English scratch takes | ~0.25 per character (assumed) |
| `eleven_v4_turbo` | 90+ | Real-time v4 over a WebSocket only. This tool does not use it | not measured |

ElevenLabs now lists `eleven_turbo_v2_5` and `eleven_turbo_v2` as superseded by the flash models: same output, lower latency. Use flash.

### eleven_v4 limits

- Voice settings: only `stability` and `similarity_boost`. No `style`, no `speed`. The tool refuses the others before calling.
- No SSML. Direct the delivery with audio tags in the text instead.
- Whether it accepts `--prev` and `--next` is not yet tested. If ElevenLabs rejects them, the call fails with "Nothing was charged". Stitch with `eleven_multilingual_v2` then.
- Pitch drift was seen on `eleven_v3`. Not yet checked on v4, so still check the pitch of a take.

`language_code` (ISO 639-1, such as `en`, `fr`, `ar`) is ignored by models that do not support it, and is not supported on `eleven_multilingual_v2`.

## Pitch drift on eleven_v3

`eleven_v3` can move a voice away from its speaker. A male library voice came back female on v3 (median pitch 216 Hz), and sounded right on `eleven_multilingual_v2` (106 Hz). Check the pitch of a take, for example with `ffmpeg` or any audio tool, before building on it. Use `eleven_multilingual_v2` for a voice that drifts.

## Measured rates

On a Creator plan, `eleven_v4` cost 6 credits for 53 characters, exact from history (2026-10-12, one call). `eleven_v3` and `eleven_multilingual_v2` both cost about 0.45 credits per character: 66 for 151 characters, 51 for 115, and many short lines agree. The flash and turbo figure of 0.25 is half of that, assumed and not yet measured. The ledger's measured column, taken from ElevenLabs' history, is the figure to trust.

## Voice settings

Pass as JSON: `--settings '{"stability":0.5,"similarity_boost":0.75}'`.

| Field | Range | Default | Effect |
| :-- | :-- | :-- | :-- |
| `stability` | 0 to 1 | 0.5 | Lower is more expressive and less predictable. Higher is steady |
| `similarity_boost` | 0 to 1 | 0.75 | Closer to the original voice. Too high can bring out artifacts |
| `style` | 0 to 1 | 0 | Exaggerates the voice's style. Not on v4 models |
| `speed` | 0.25 to 4 | 1 | Speaking rate. Not on v4 models |
| `use_speaker_boost` | true or false | true | Clarity post-processing. Leave it on unless it causes artifacts |

Starting points: narration `stability 0.7, similarity_boost 0.5`; conversational `0.4, 0.75, style 0.3`; news `0.8, 0.6`. Change one value at a time, on a scratch take.

## Request stitching

`eleven_v3` rejects `previous_text` and `next_text` with a 400 ("not yet supported"), and the tool refuses `--prev`/`--next` on it before calling. Stitch with `eleven_multilingual_v2`.

Long scripts are made one line per request. Without context the joins can pop, pause or change tone. Pass the line before as `--prev` and the line after as `--next`. Each request then knows its neighbours, and the takes sound like one read. Redo a single line by repeating its call with the same `--prev` and `--next`.

## Output formats

`--format` sets `output_format`. Common values:

| Format | Notes |
| :-- | :-- |
| `mp3_44100_128` | Default. Good for almost everything |
| `mp3_44100_192` | Higher quality MP3, Creator plan and up |
| `mp3_44100_64`, `mp3_22050_32` | Smaller files |
| `wav_44100` | Uncompressed, with a header |
| `pcm_16000` … `pcm_48000` | Raw PCM, no header. 44100 and 48000 need Pro and up |
| `opus_48000_64` | Efficient compressed |
| `ulaw_8000`, `alaw_8000` | Telephony |

The cache key includes the format, so changing it is a new request.

## Pace

Natural narration runs at about 2.6 words per second. A 6 second window holds about 15 words. Check the fit on paper first, then with a flash take and `--timestamps`.

## Errors

401 is a bad key or a missing permission, 422 an invalid field (nothing is charged), 429 too many requests at once.
