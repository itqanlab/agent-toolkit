# higgsfield-studio

Make images, video, audio, 3D and ads with Higgsfield from the agent, and spend the credits on purpose. Seven more skills come in the same plugin: Soul ID, product photoshoots, marketplace cards, brand kits, YouTube thumbnails, video explainers and websites.

## Just ask

Once the plugin is installed, say what you want in your own words:

> *"make a vertical 5 second video from this product photo"*
> *"draw three logo ideas for my cafe"*
> *"reframe this video to 9:16"*
> *"make a UGC ad for this product link"*
> *"score this video's hook before I post it"*
> *"make a 3D model from these four photos"*
> *"how many Higgsfield credits are left, and what did we spend this week?"*

The agent runs the commands, tells you what each job will cost before it spends anything, and hands you the files.

The one thing it cannot do for you is sign in. You run `higgsfield auth login` once and finish in the browser. No key or password ever passes through the chat.

## Why this exists

Higgsfield is paid by the credit, and video burns them fast: one default Seedance 2.5 clip was quoted at 35 credits, and a 12-second one at 84. Higgsfield's own agent skills tell the agent not to price jobs in advance. This plugin does the opposite and puts guards around every paid job.

| Guard | What it does |
| :-- | :-- |
| Price | Higgsfield prices every job for free before it runs. `--dry` shows the price and runs nothing. `--max` refuses above a limit |
| Cache | The same request, with the same files, returns what was already paid for, at 0 credits |
| Measure | The real cost is read from Higgsfield's transaction list and written to a ledger next to the price |
| Reserve | A job that would leave fewer than 5 credits is refused (`HF_RESERVE` changes it) |
| Ask | Deploying or publishing a website, training a Soul or changing the billing workspace needs your yes |

It also keeps a working order that moves from cheap to expensive: draft on a model that costs a fraction of a credit, settle the first frame as an image before animating it, and test 5 seconds before 12.

## Requirements

**Node 18 or newer, and Higgsfield's command line tool.** If either is missing, the skill offers to install it:

```bash
sh scripts/setup-deps.sh --check    # is everything present?
sh scripts/setup-deps.sh            # show the install command, ask, then run it
```

```powershell
.\scripts\setup-deps.ps1            # Windows
```

The tool installs with `npm install -g @higgsfield/cli` on every system. On macOS and Linux, Higgsfield's own installer works too.

**A Higgsfield account.** Sign in once with `higgsfield auth login`. Soul training needs a paid plan.

The brand kit and website skills use Python 3 for their local tools. Their own `references/prerequisites.md` lists the rest.

## If you prefer the command line

```bash
node scripts/hf.mjs check                                   # installed and signed in?
node scripts/hf.mjs account                                 # credits, reserve, recent spends
node scripts/hf.mjs cost seedance_2_5 --prompt "..." --duration 5
node scripts/hf.mjs create z_image --prompt "a red apple" --out apple.png --max 1
node scripts/hf.mjs workflow reframe --video in.mp4 --aspect_ratio 9:16 --resolution 720p --out out.mp4 --dry
node scripts/hf.mjs run model list --video                  # any free command
node scripts/hf.mjs ledger                                  # what has been spent
```

Paid commands: `create`, `workflow`, `photoshoot`, `cards`, `dtc`. Outward ones go through `act ... --yes`.

## Where things are kept

`.higgsfield/` in the folder you run from: `ledger.jsonl` (keep it), `uploads.json` (files already uploaded, so each is sent once) and `cache/` (the media, add it to `.gitignore`). `HIGGSFIELD_HOME` moves the folder.

## Example

These are real runs, from 2026-10-12.

```
$ node scripts/hf.mjs create z_image --prompt "a red apple on a wooden table, soft daylight" --max 1 --out apple.png
create:z_image: quote 0.15 credits (from Higgsfield, before running)   cache 56593da6e1309100
done. measured 0.15 credits (from transactions) (quote 0.15), 72.1 left.
  -> apple.png

$ node scripts/hf.mjs create z_image --prompt "a red apple on a wooden table, soft daylight" --max 1 --out apple-again.png
create:z_image: already paid for, costs 0   cache 56593da6e1309100
cache hit, 0 credits. Paid on 2026-10-12T20:35:35.443Z.
```

## Disclosure

Generated images, video and voice count as AI-generated material on most social platforms. Use each platform's AI label when you publish them.

## Credits

Built on [Higgsfield's official agent skills](https://github.com/higgsfield-ai/skills), used under the MIT License. Their guides are in each skill's `references/` without changes. See [`references/ATTRIBUTION.md`](references/ATTRIBUTION.md).

## Install

Claude Code:

```
/plugin marketplace add itqanlab/agent-toolkit
/plugin install higgsfield-studio@itqan
```

Any other agent (installs all eight skills of the plugin):

```bash
./scripts/install.sh higgsfield-studio
```
