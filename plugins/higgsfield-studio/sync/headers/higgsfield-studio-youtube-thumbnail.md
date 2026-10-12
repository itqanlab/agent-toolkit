---
name: higgsfield-studio-youtube-thumbnail
description: "Make high-click-through YouTube thumbnails and Shorts or Reels covers with Higgsfield, keeping faces and logos true. Triggers: 'make a YouTube thumbnail', 'thumbnail for this video', 'MrBeast-style cover', 'Shorts cover', 'Instagram video cover', 'change the face expression on my thumbnail'. Part of Higgsfield Studio: every render is priced first, never paid for twice, and written to a ledger. Needs Node 18+ and the higgsfield command line tool."
license: MIT
compatibility: "Requires Node 18 or newer and the Higgsfield command line tool, through the higgsfield-studio skill in the same plugin. Needs network access and a Higgsfield account. Generating spends its credits."
metadata:
  author: itqanlab
  version: 1.0.0
  category: media
  display: "Higgsfield YouTube Thumbnail"
  short: "Thumbnails and video covers, priced first"
  starter: "make a YouTube thumbnail for my video about saving money"
---

# Higgsfield YouTube Thumbnail

A truthful concept first, then one render per variant, then small edits on the one the user picks.

## What it costs

The main render is `nano_banana_pro` at 4K, quoted at 4 credits for 16:9 on 2026-10-12. A set of four variants is about 16 credits, and Higgsfield's guide allows up to 16 renders, which would be about 64. Offer one render first, or ask before a set. Small edits on the picked image use `seedream_v5_pro` at 2k (quoted at 2.5).

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
