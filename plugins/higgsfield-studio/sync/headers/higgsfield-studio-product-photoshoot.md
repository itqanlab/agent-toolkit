---
name: higgsfield-studio-product-photoshoot
description: "Make brand-quality product photos with Higgsfield: studio, lifestyle, Pinterest pins, hero banners, carousels, ad packs and try-ons. Triggers: 'product photo', 'studio shot of my product', 'lifestyle image of this bottle', 'make a Pinterest pin', 'hero banner for my site', 'ad creative pack', 'model wearing my product', 'restyle this photo for Christmas'. Part of Higgsfield Studio: each shoot is planned and priced for free before any image is made, never paid for twice, and written to a ledger. Needs Node 18+ and the higgsfield command line tool."
license: MIT
compatibility: "Requires Node 18 or newer and the Higgsfield command line tool, through the higgsfield-studio skill in the same plugin. Needs network access and a Higgsfield account. Generating spends its credits."
metadata:
  author: itqanlab
  version: 1.1.0
  category: media
  display: "Higgsfield Product Photoshoot"
  short: "Product photos priced before they are made"
  starter: "make three lifestyle shots of this bottle for Instagram"
---

# Higgsfield Product Photoshoot

Higgsfield writes the final image prompt from a mode and a short intent, then renders each image. The guard plans the shoot first with Higgsfield's free `--enhance-only` step and prices every planned image, so the user sees the full price before anything is made.

## What it costs

Each image is a `gpt_image_2` render at 2k, quoted at 6.5 credits on 2026-10-12. A `--count 2` shoot was quoted at 13. `--count 5` is about 33 credits. Start with `--count 1`, show it, then make more.

```
node ../higgsfield-studio/scripts/hf.mjs photoshoot --mode lifestyle_scene --prompt "cold-brew bottle on a sunlit kitchen counter" --image bottle.jpg --count 1 --dry
node ../higgsfield-studio/scripts/hf.mjs photoshoot --mode lifestyle_scene --prompt "cold-brew bottle on a sunlit kitchen counter" --image bottle.jpg --count 1 --max 8 --out shoot/ --tag launch --why "first lifestyle shot"
```

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
