# image-prompt

Write image prompts in the project's brand, sized for each platform, ready for any image generator.

## Just ask

Once the skill is installed, say what you want in your own words:

> *"write a prompt for an Instagram post of our new tote bag"*
> *"make it a close-up of the stitching, for a story"*
> *"give me a prompt I can paste into ChatGPT, with our product photo as reference"*
> *"write a product page image prompt, but ignore the brand this time"*

The agent writes the prompt, shows it to you, and says where it saved it. Nothing is generated and nothing is spent. To make the image, hand the prompt to an image generator: the `higgsfield-studio` skill when it is installed, which prices every job first, or any web tool by paste.

## Why this exists

A good image prompt carries a lot: the brand's colours and look, the right size for the platform, what to avoid, and a line that stops the model from handing a reference photo back unchanged. Writing that by hand every time is slow, and it drifts. This skill builds it the same way every time, from the brand file the project already keeps, and keeps a log so the same prompt is not written twice.

## Requirements

**Node 18 or newer.** If you do not have it, the skill offers to install it:

```bash
sh scripts/setup-deps.sh --check    # is everything present?
sh scripts/setup-deps.sh            # show the install command, ask, then run it
```

```powershell
.\scripts\setup-deps.ps1            # Windows
```

It works offline and needs no account.

## The brand file

Keep a `brand.md` in the project (or pass `--brand FILE`). Sections are found by their headings: palette, photography, studio, motion, tone and don't. The full contract and an example are in [`references/brand-file.md`](references/brand-file.md). Without one, prompts carry no brand style.

## If you prefer the command line

```bash
node scripts/prompt.mjs sizes
node scripts/prompt.mjs brand
node scripts/prompt.mjs --subject "a tan leather tote bag" --platform instagram_post --variant portrait --people --paste ChatGPT
```

Each run writes `prompt.txt`, `prompt.json` and, with `--paste`, `PASTE.md` to a dated folder under `.prompts/` (or `--out DIR`). `.prompts/log.jsonl` is the log the duplicate check reads. Keep it.

## Install

Claude Code:

```
/plugin marketplace add itqanlab/agent-toolkit
/plugin install image-prompt@itqan
```

Any other agent:

```bash
./scripts/install.sh image-prompt
```
