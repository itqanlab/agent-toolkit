# elevenlabs-studio

Make voice-over, sound effects and music with ElevenLabs from the agent, and spend the credits on purpose.

## Just ask

Once the skill is installed, say what you want in your own words:

> *"connect my ElevenLabs account"*
> *"find a calm English narrator and let me hear a few"*
> *"make a voice-over for this script, one file per line"*
> *"I need a 2 second whoosh for the transition"*
> *"make a 45 second background track that matches these scenes"*
> *"how many credits are left, and what did we spend this week?"*

The agent runs the commands, tells you what each step will cost before it spends anything, and hands you the files.

The one thing it cannot do for you is create the key. You make it on the ElevenLabs website and paste it into a file. That way the key never passes through a chat window. The agent walks you through it.

## Why this exists

ElevenLabs is paid by the credit, and it is easy to waste them: asking twice for the same line, generating test sentences to choose a voice, rendering a whole script to fix one word, or a loop that keeps going. This skill puts four guards around every paid call.

| Guard | What it does |
| :-- | :-- |
| Cache | The same request returns the file already paid for, at 0 credits |
| Estimate | Every call is priced first from a rate table, partly published and partly measured. `--dry` shows the price and calls nothing. `--max` refuses above a limit |
| Measure | The real cost goes in a ledger next to the estimate. Voice-over is measured exactly from ElevenLabs' history; other calls from the balance before and after |
| Reserve | A call that would leave fewer than 1000 credits is refused (`ELEVEN_RESERVE` changes it) |

It also keeps a working order that moves from free to expensive: choose the voice from free samples, fit the script on paper, check the timing with a half-price take, then make the final take one line at a time. Music starts from a free plan and is rendered once.

## Requirements

**Node 18 or newer.** If you do not have it, the skill offers to install it:

```bash
sh scripts/setup-deps.sh --check    # is everything present?
sh scripts/setup-deps.sh            # show the install command, ask, then run it
```

```powershell
.\scripts\setup-deps.ps1            # Windows
```

**An ElevenLabs account and API key.** Create the key at https://elevenlabs.io/app/settings/api-keys with **Text to Speech**, **Sound Effects**, **Music**, **Voices (read)** and **User (read)** switched on. User read lets the tool read your credit balance, and it will not spend credits it cannot count. If there is a History row, set it to Read too, so voice-over costs are measured exactly. A credit quota on the key is a good extra limit.

## Setup

```bash
node scripts/setup.mjs begin      # creates the file and prints the steps
node scripts/setup.mjs finish     # checks the key, shows plan and credits
node scripts/setup.mjs status     # is it connected, and how much is left
```

The key is stored with the other toolkit credentials, in `credentials/elevenlabs.env` under `~/.itqan-agent-toolkit` (or `AGENT_TOOLKIT_HOME`). Storage comes from [`toolkit-credentials`](../toolkit-credentials).

## If you prefer the command line

```bash
node scripts/eleven.mjs account
node scripts/eleven.mjs voices --library --q "calm narrator" --lang en --previews ./previews

node scripts/eleven.mjs tts --voice JBFqnCBsd6RMkjVDRZzb --model eleven_flash_v2_5 \
  --text "Every project starts with a question." --timestamps --out scratch/l1.mp3 --dry
node scripts/eleven.mjs tts --voice JBFqnCBsd6RMkjVDRZzb --model eleven_multilingual_v2 \
  --text "Every project starts with a question." --next "Ours was simple." \
  --out vo/l1.mp3 --tag launch-video --why "final take, line 1"

node scripts/eleven.mjs sfx --text "soft airy whoosh, left to right" --duration 1.8 --out sfx/whoosh.mp3

node scripts/eleven.mjs plan --prompt "warm minimal piano, slow build" --ms 45000 --out music/plan.json
node scripts/eleven.mjs music --plan music/plan.json --out music/bed.mp3 --max 700

node scripts/eleven.mjs ledger
```

Every paid command takes `--dry`, `--max N`, `--fresh` (with `--why`), `--tag`, `--why` and `--out`.

## Where things are kept

Each project gets a `.elevenlabs/` folder in the directory you run from:

```
.elevenlabs/
  ledger.jsonl    every paid call: what, why, tag, estimate, measured cost
  cache/          the audio, named by request hash
```

Keep the ledger. Add the cache to `.gitignore`:

```
.elevenlabs/cache/
```

`ELEVENLABS_HOME` moves the folder.

## Example

The numbers below are illustrative.

```
$ node scripts/eleven.mjs sfx --text "soft UI confirmation tick" --duration 0.6 --out tick.mp3
sfx: estimate ~7 credits (from the rate table, not a quote)   cache 9f2c41d07a3b5e18
done. measured 7 credits (estimate 7), 41193 left. -> tick.mp3

$ node scripts/eleven.mjs sfx --text "soft UI confirmation tick" --duration 0.6 --out tick.mp3
sfx: estimate ~7 credits (from the rate table, not a quote)   cache 9f2c41d07a3b5e18   HIT, would cost 0
cache hit, 0 credits. -> tick.mp3
```

## Disclosure

Synthesized voice and generated music count as AI-generated material on most social platforms. Use each platform's AI label when you publish them.

## Credits

The API reference tables in `references/` are adapted from the [ElevenLabs agent skills](https://github.com/elevenlabs/skills) under the MIT License. See [`references/ATTRIBUTION.md`](references/ATTRIBUTION.md).

## Install

Claude Code:

```
/plugin marketplace add itqanlab/agent-toolkit
/plugin install elevenlabs-studio@itqan
```

Any other agent:

```bash
./scripts/install.sh elevenlabs-studio
```
