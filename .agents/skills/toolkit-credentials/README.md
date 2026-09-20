# toolkit-credentials

One place for API keys and tokens, shared by every skill in this toolkit, on macOS, Windows and Linux.

Without a shared convention each skill invents its own credential handling, and the user ends up pasting secrets into a chat window — where they land in a transcript, and usually in a log file too. This skill replaces that with a flow where **the secret is never typed into the conversation**: the agent creates an empty file, the user pastes the value into it, the agent checks that something is there and makes one test call.

It is aimed squarely at people who are not engineers. The setup instructions name the exact button to click and every permission to tick, and the failure messages say what to do next rather than quoting an error code.

## Just ask

You do not run this yourself. When a skill needs a credential it invokes this one, and the agent walks you through it:

> *"connect my Cloudflare account"*
> *"where are my tokens stored?"*
> *"the skill says my credential is missing"*

You will be asked to do exactly one thing by hand: open a file and paste a value into it. That is the whole point — a secret pasted into a chat window ends up in a transcript and usually a log file, so the agent creates an empty file, tells you its name, and never sees the value except inside a running script.

Everything below is for people who would rather drive themselves.

## Requirements

**Node 18 or newer.** If you do not have it, this installs it for you:

```bash
sh scripts/setup.sh --check    # is it present and new enough?
sh scripts/setup.sh            # show the install command, ask, then run it
```

```powershell
.\scripts\setup.ps1            # Windows
```

It picks the right command for your machine (Homebrew, apt, dnf, pacman, zypper, apk, winget) and never installs anything without asking — add `--yes` to skip the question. Where there is no package manager it prints instructions you can follow, including a route that needs no admin rights.

Nothing else is required. The scripts use only the Node standard library, so a skill directory copied anywhere keeps working with no install step.

## Where credentials are stored

```
~/.itqan-agent-toolkit/
  credentials/
    cloudflare.env
    hetzner.env
  state/
    setup.json
```

The name carries the publisher prefix on purpose. `agent-toolkit` on its own is a generic phrase another project could claim, and two tools quietly sharing one credential directory is a bad afternoon. One folder, one product, obvious what created it and obvious how to remove it.

Set `AGENT_TOOLKIT_HOME` to put the store somewhere else — useful for an organisation that wants everything under one directory:

```bash
export AGENT_TOOLKIT_HOME="$HOME/.acme/agent-toolkit"
```

```powershell
setx AGENT_TOOLKIT_HOME "$env:USERPROFILE\.acme\agent-toolkit"
```

Directories are created mode 700 and files 600 on macOS and Linux. Windows does not enforce Unix permissions; `status` says so rather than implying protection that is not there.

## If you prefer the command line

Normally you do not run this directly — a skill that needs a credential invokes it for you. To inspect or repair a setup:

```bash
node scripts/store.mjs status
node scripts/store.mjs has cloudflare CLOUDFLARE_API_TOKEN
node scripts/store.mjs path
```

`status` lists what is configured and when it was last verified. `has` reports whether a value is present and how many characters it is — enough to spot a truncated paste — and never prints the value itself.

There is no command that prints a secret. That is deliberate, not an omission.

## Example

```
$ node scripts/store.mjs has cloudflare CLOUDFLARE_API_TOKEN
CLOUDFLARE_API_TOKEN: empty — the file is ready but nothing has been pasted in yet
  open: /Users/you/.itqan-agent-toolkit/credentials/cloudflare.env

$ node scripts/store.mjs status
store: /Users/you/.itqan-agent-toolkit
  (default location)

  cloudflare     configured   last verified: 2026-08-11T11:04:22Z
```

## For skill authors

A skill that needs a credential copies `scripts/store.mjs` into its own `lib/` directory — skill directories have to work standalone wherever they are copied — and imports from it:

```js
import { readSecrets } from './lib/store.mjs';
const { CLOUDFLARE_API_TOKEN } = readSecrets('cloudflare');
```

Copy the file verbatim. Every skill agreeing on the same file format and location is the entire point.

`SKILL.md` has the full contract: the setup flow, how to write instructions someone non-technical can follow, and how to let a provider mint its own credential so the user ticks a few boxes instead of hundreds.

## Install

Claude Code:

```
/plugin marketplace add itqanlab/agent-toolkit
/plugin install toolkit-credentials@itqan
```

Any other agent:

```bash
./scripts/install.sh toolkit-credentials
```
