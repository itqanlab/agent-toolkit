---
name: higgsfield-studio-video-explainer
description: "Make a narrated explainer or story video with Higgsfield from a topic or document, in 10-second blocks with one style and one narrator. Triggers: 'make an explainer video', 'explain this in a video', 'turn this document into a narrated video', 'tell this story as an animated video', 'make a faceless narrated video', 'show me explainer styles'. Part of Higgsfield Studio: the whole video is priced block by block before anything is made, and every job is written to a ledger. Needs Node 18+ and the higgsfield command line tool."
license: MIT
compatibility: "Requires Node 18 or newer and the Higgsfield command line tool, through the higgsfield-studio skill in the same plugin. Needs network access and a Higgsfield account. Generating spends its credits."
metadata:
  author: itqanlab
  version: 1.1.0
  category: media
  display: "Higgsfield Video Explainer"
  short: "Narrated explainer videos, priced block by block"
  starter: "make a 30-second explainer about how our app works"
---

# Higgsfield Video Explainer

One style, one narrator, one voice take and one clip per 10-second block, then Higgsfield joins them.

## What it costs

This is the most expensive skill in the plugin. Each 10-second clip is `gemini_omni` at 10 seconds, quoted at 30 credits on 2026-10-12. Each voice take (`seed_audio`) was quoted at 0.1. So a 30-second explainer is about 91 credits and a one-minute one about 182, before the final assembly. The assembly model, `explainer_video`, was not in Higgsfield's model list on 2026-10-12, so it may not be priced in advance and may need `--yes`.

Before writing any block, tell the user the number of blocks and the total, and get a yes. Make and approve every voice take (cheap) before any clip (expensive). Never re-render a clip to fix the narration.

## Before anything else

```
sh ../higgsfield-studio/scripts/setup-deps.sh --check
node ../higgsfield-studio/scripts/hf.mjs check
```

The first checks Node and the `higgsfield` tool, and `sh ../higgsfield-studio/scripts/setup-deps.sh` installs what is missing after asking. The second checks the sign-in. If Higgsfield is not signed in, the user signs in once with `higgsfield auth login`, which opens the browser. Never print the sign-in token or open the CLI's credential file.

## Spending credits

This skill is part of the Higgsfield Studio plugin. Every paid command runs through the main skill's guard, `node ../higgsfield-studio/scripts/hf.mjs`. It asks Higgsfield for the price before running, refuses above `--max` or below the reserve, never pays twice for the same request, and writes what each job really cost to `.higgsfield/ledger.jsonl` in the project. The full rules are in `../higgsfield-studio/SKILL.md`. The short form:

- Price first with `--dry`, using every parameter the real job will use. Tell the user the total for anything over about 5 credits.
- Put `--max N` (a little above the price), `--tag` and `--why "..."` on every paid job.
- Ask before spending more than about 10 credits, or 10% of what is left. `node ../higgsfield-studio/scripts/hf.mjs account` shows the balance.
- Anything outward or not undoable goes through `act` and needs `--yes`. Say what will happen and wait for the user's yes before adding it.
- Report in plain words, in the user's language: where the file is, what it cost, what is left. No JSON or job ids unless asked.

Free commands, such as lists, `model get`, presets and uploads, can run as `node ../higgsfield-studio/scripts/hf.mjs run <command>` or as `higgsfield <command>` directly.

## Updates

This skill is versioned with its plugin. Its version is `metadata.version` in the header of this file. The plugin's history, for every skill in it, is in `../higgsfield-studio/CHANGELOG.md`. To check for a newer version, open the address on its `Latest:` line and compare the top version with this one. Read every entry in between and tell the user what changed before anything is updated.
