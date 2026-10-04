# Music

API facts for `node scripts/eleven.mjs plan` and `music`. Parts adapted from the ElevenLabs agent skills (MIT, see `ATTRIBUTION.md`).

## Endpoints

- `POST /v1/music/plan` makes a composition plan from a prompt. ElevenLabs documents it as costing no credits. It is rate-limited. Body: `prompt`, `music_length_ms` (3,000 to 600,000), `model_id`.
- `POST /v1/music?output_format=...` renders audio from either a `prompt` with `music_length_ms`, or a `composition_plan`. Never both.

## Which model

| Model | Section lengths | Plan shape |
| :-- | :-- | :-- |
| `music_v1` | Held to each `duration_ms` with `respect_sections_durations: true` | `sections` |
| `music_v2`, `music_v2_5` | Ignored. `respect_sections_durations` has no effect | `chunks` |

The tool defaults to `music_v1` for that reason: music that has to land on a cut needs its sections to keep their lengths. Use v2 only for music that does not have to match a picture, and make the plan with the same `--model` you render with. The tool warns when the plan shape and the model do not match.

## Plan shape for `music_v1`

This is what `plan --model music_v1` returns. Check a real one before writing your own, because ElevenLabs may add fields.

```json
{
  "positive_global_styles": ["warm piano", "slow", "minimal"],
  "negative_global_styles": ["drums", "vocals"],
  "sections": [
    {
      "section_name": "Intro",
      "positive_local_styles": ["sparse", "soft"],
      "negative_local_styles": [],
      "duration_ms": 12000,
      "lines": []
    }
  ]
}
```

Global styles set the whole piece. Local styles shape one section. `lines` holds lyrics, and stays empty for instrumental music. The estimate is the sum of every `duration_ms`.

## Plan shape for v2 models

An ordered list of `chunks`, up to 30, each 3,000 to 120,000 ms, 3 s to 10 min in total. Each chunk has `text` (section label, lyrics, cues such as `{guitar solo}`), `duration_ms`, `positive_styles`, `negative_styles` and `context_adherence` (`low`, `medium` or `high`). Put genre and instrumentation in the styles, not the text. The first chunk's styles set the tone of the whole piece.

## Working with a plan

1. `plan --prompt "..." --ms <total> --out plan.json`. Free.
2. Edit `plan.json`: one section per scene, each `duration_ms` equal to that scene's length.
3. `music --plan plan.json --out bed.mp3 --dry` to see the estimate, then render once.

## Cost

About 825 credits per minute, measured (a 44.5 s `music_v1` render cost 612). The published figure was 900. A 45 second bed is about 620 credits, so always pass `--max`.

## Restrictions

Prompts cannot name artists, bands or copyrighted lyrics. A refused prompt comes back with a suggested rewording in the error.

## Output formats

`mp3_44100_128` is the default here. `music_v1` also accepts the usual MP3, PCM and Opus formats; v2 models offer `mp3_48000_192` and higher.
