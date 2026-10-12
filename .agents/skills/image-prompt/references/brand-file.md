# The brand file

The project owns its brand. This skill only reads it. Nothing about any brand is written in the skill: every style value in a prompt comes from this file, read fresh each time.

## Where it is looked for

In this order, the first one found wins:

1. `--brand FILE` on the command.
2. The `BRAND_FILE` environment variable.
3. In the folder the command runs from: `brand.md`, `BRAND.md`, `brand/brand.md`, `docs/brand.md`.

No file is fine. The prompt then carries no brand style, and the tool says so.

## What it contains

Plain Markdown. A `# ` title is taken as the brand name. Each `## ` section is found by a word in its heading, so the headings can be in your own words. Each line or bullet under a heading becomes one short clause in the prompt. Write them as you would say them to a photographer.

| Section | A heading that matches | Used for |
| :-- | :-- | :-- |
| Palette | Palette, Colours, Colors | `[PALETTE]`: name each colour, a hex code helps |
| Look | Photography, Visual, Look, Imagery, Style | `[STYLE]` on every shot: light, mood of the picture, materials |
| Studio | Studio, Product shots, Catalog | `[STYLE]` on studio and detail shots only: background and set rules |
| Motion | Motion, Movement, Camera, Video | `[BRAND MOTION]` on video prompts: pace and camera rules |
| Tone | Tone, Voice, Mood, Personality | `[MOOD]`: adjectives that apply to a picture |
| Don't | Don't, Avoid, Never, Not to | `[AVOID]`: kept exactly as written |

Keep studio-only rules ("seamless white background", "no models") under **Studio**. Under **Look** they would also land on editorial and lifestyle shots, where they fight the scene.

## Example

```markdown
# Acme Leather

## Palette
- Warm cognac brown (#5a3a20)
- Cream (#e6d4b8)

## Photography
- Natural, warm light
- Soft shadows, never hard ones

## Studio
- Seamless warm off-white background
- No props

## Motion
- Slow, deliberate moves. No fast zooms

## Tone
- Quiet, refined, unhurried

## Don't
- No text overlays
- Never use neon colours
```

`node scripts/prompt.mjs brand` shows which file is used and how many lines each section gave.

## Brand modes

| `--brand-mode` | What the prompt carries |
| :-- | :-- |
| `full` (default) | Look (and Studio on studio shots), Palette, Tone, Motion on video, and the Don't list |
| `minimal` | Look (and Studio on studio shots) and the Don't list |
| `none` | Nothing from the brand. The file is not read |

## The prompt log

Every prompt written is logged in `.prompts/log.jsonl` in the folder the command runs from (`PROMPTS_HOME` moves it), and its files go in a dated folder beside it unless `--out` says otherwise. Before writing, the tool checks the log. The exact same request, or one for the same platform in the last 30 days whose words overlap by 60% or more, stops it with exit code 3 and the earlier folder. Reuse that, or pass `--force`. Image and video prompts share the log but are compared only with their own kind.
