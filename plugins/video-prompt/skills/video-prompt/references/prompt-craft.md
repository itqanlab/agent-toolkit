# Writing video prompts that work

What the script does for you, and what to add by hand when a first clip misses.

## The shape

Every prompt is built in labelled lines: `[SUBJECT]`, `[PEOPLE]` when asked, `[SCENE]`, `[MOTION]`, the brand lines (`[STYLE]`, `[PALETTE]`, `[MOOD]`, `[BRAND MOTION]`), `[CAMERA]`, `[AVOID]`, and `[LENGTH]`. Motion gets its own line because it is where video models go wrong most: too fast, too much, or the subject melting as it moves.

## Choosing the type

| Type | Use it for |
| :-- | :-- |
| `turntable` (default) | Product pages and catalog posts: a slow turn or a floating lift in a clean studio |
| `hero-reveal` | Launches and the first second of a reel: a push-in or a reveal that ends on a clean still frame |
| `editorial` | Feed reels and stories: a cinematic scene built around the subject |
| `detail` | Texture moments: a slow macro glide across the surface |
| `animate-still` | Bringing an existing photo to life with subtle motion. Always uses the photo as reference |

## Length

Each platform has its own range, and the tool refuses a length outside it. Short clips are cheaper and fail less: 5 to 10 seconds is the sweet spot for most models. Higgsfield's default video model makes 4 to 30 seconds per clip, so a longer piece is planned as several clips of equal length, and `prompt.json` says how many.

## Draft first

Video is the expensive part. `prompt.json` names a draft model as well as the final one. Make the draft, check the motion and framing, then render the final once.

## When the first clip misses

Add one fix at a time:

- Too much motion: "Slow, subtle motion only. The camera barely moves."
- No motion wanted at all: "Static shot, no camera movement, only light changes."
- The product deforms as it moves: "The subject keeps its exact shape and proportions throughout."
- Text appeared: "No text, captions or watermarks at any point."
- A cut appeared: "One continuous shot, no cuts."

## Sizes

`node scripts/prompt.mjs sizes` lists every platform with its size, ratio, accepted length and default length.
