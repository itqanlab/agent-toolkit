---
name: higgsfield-studio-websites
description: "Build, edit and deploy websites, web apps and browser games that Higgsfield hosts. Triggers: 'build me a website', 'make a landing page', 'create a web app', 'make me a browser game', 'deploy this site', 'publish my site', 'make a spritesheet for my game'. Part of Higgsfield Studio: deploying, publishing and renaming happen only after the user says yes, and any generated art is priced first and written to a ledger. Needs Node 18+, git and the higgsfield command line tool."
license: MIT
compatibility: "Requires Node 18 or newer, git and the Higgsfield command line tool, through the higgsfield-studio skill in the same plugin. Game art tools in scripts/ need Python 3, and some need Blender. Needs network access and a Higgsfield account."
metadata:
  author: itqanlab
  version: 1.0.0
  category: media
  display: "Higgsfield Websites"
  short: "Websites and games hosted by Higgsfield"
  starter: "build me a one-page landing site for my bakery"
---

# Higgsfield Websites

Higgsfield creates the site and its git repository, you edit the code, and Higgsfield builds and hosts it.

## What is outward here

These change something people can see, or cannot be undone, so each runs through `act` with `--yes`, after the user agrees to that exact step:

- `website create`: makes the site and its repository on the account.
- `website deploy`: puts the current code live.
- `website publish`: lists the live site on Higgsfield's public community feed.
- `website rename`: changes the address. The old address stops working.
- `website contest`: enters the site in a public contest.
- `website secrets set` and `delete`: change the site's environment on the next deploy.
- `website repo-access`: prints a git address with a scoped token. Use it, never show the token in the chat.

Ask about deploying and publishing separately. A yes to deploy is not a yes to publish.

## What it costs

We have not measured whether creating or deploying a site spends credits. Watch the balance with `node ../higgsfield-studio/scripts/hf.mjs account` before and after the first deploy, and tell the user. Images, video, sound and music made for the site go through the guard like any other job.

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
