# Writing image prompts that work

What the script does for you, and what to add by hand when a first image misses.

## The shape

Every prompt is built in labelled lines, in this order: `[SUBJECT]`, `[PEOPLE]` when asked, `[SCENE]`, the brand lines (`[STYLE]`, `[PALETTE]`, `[MOOD]`), `[TEXT]` for a headline, `[CAMERA]`, `[AVOID]`, then one closing line with the ratio and pixel size. Image models follow labelled lines better than a paragraph, and a person can edit one line without touching the rest.

## With a reference image

Pass `--reference` when the user has a photo of the real product. The prompt then opens by telling the model to keep the subject exactly and build a new scene around it. Without that line, image models often hand the reference back almost unchanged. The suggested Higgsfield model switches to one made for edits with references.

## Choosing the type

| Type | Use it for | Text on the image |
| :-- | :-- | :-- |
| `editorial` (default) | Feed and story posts that must stop the scroll. Add `--people` for a person with the subject | None |
| `clean-studio` | Product pages, catalogs, plain product posts | None |
| `detail` | Close-ups of material and texture, for variety and story inserts | None |
| `branded-overlay` | Announcements. Leaves empty space for a headline; `--headline "..."` asks the model to set it | One short line |

Vary the type across a series, so a feed does not look the same post after post: an editorial first, a detail next, a studio shot for the product page.

## One frame for several crops

When one image must serve a 9:16 story and a 1:1 post, ask for 9:16 and add to `--scene`: keep the subject inside the middle 56% of the frame, and leave the top and bottom fifth as plain scene. The square crop then loses nothing that matters.

## When the first image misses

Add one fix at a time, then make one more image:

- Text or a watermark appeared: "No text, no letters, no watermarks anywhere in the image."
- The product changed shape or colour: "Keep the exact product from the reference: same shape, colour, stitching and hardware."
- The background is busy: "Plain, uncluttered background."
- The framing is off: "Centred composition, a single subject, room around it."
- It looks artificial: "Natural skin and materials, no heavy retouching."

## Sizes and ratios

`node scripts/prompt.mjs sizes` lists every platform. A model that cannot make the exact ratio gets the nearest one it is likely to accept, and `prompt.json` says what to crop to afterwards (`higgsfield.crop_to`).
