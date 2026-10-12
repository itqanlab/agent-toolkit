---
name: higgsfield-studio-brandkit
description: "Build a complete brand identity with Higgsfield: logo marks, palette, type, mockups, packaging, signage, social graphics and an editable brandbook. Triggers: 'create a brand kit', 'make a visual identity', 'design a logo and brandbook', 'apply this logo to branded assets', 'make packaging or signage', 'extend our existing branding'. Part of Higgsfield Studio: every image is priced first, never paid for twice, and written to a ledger. Needs Node 18+, Python 3 and the higgsfield command line tool."
license: MIT
compatibility: "Requires Node 18 or newer and the Higgsfield command line tool, through the higgsfield-studio skill in the same plugin, and Python 3 for the local brandbook tools (see references/prerequisites.md). Needs network access and a Higgsfield account. Generating spends its credits."
metadata:
  author: itqanlab
  version: 1.0.0
  category: media
  display: "Higgsfield Brand Kit"
  short: "A brand identity and brandbook, on a budget"
  starter: "create a brand kit with a logo, palette and brandbook for my cafe"
---

# Higgsfield Brand Kit

A brand system built in stages, with approvals saved in the project, so only what depends on a change is made again. Logos are drawn with `recraft_v4_1` (quoted at 1.25 credits on 2026-10-12), mockups and scenes with other image models, and the brandbook is assembled locally by the Python tools in `scripts/`, which cost nothing.

## What it costs

A full kit is many images. Before starting, list the deliverables the user wants, price one image of each kind with `--dry`, and give the user a total. Make logo candidates one at a time and let the user pick before any mockup is made.

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
