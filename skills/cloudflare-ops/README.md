# cloudflare-ops

Connect a Cloudflare account once, then let the agent manage DNS, subdomains, Pages and R2 — without opening the dashboard again.

## Just ask

You do not need to run anything. Once the skill is installed, say what you want in your own words and the agent does it:

> *"connect my Cloudflare account"*
> *"point app.mysite.com at my server, the address is 203.0.113.10"*
> *"has the DNS updated yet?"*
> *"what domains do I have?"*
> *"publish this site to Cloudflare and put www.mysite.com on it"*
> *"delete the old staging subdomain"*

The agent runs the commands, checks the result, and tells you in plain words whether it worked. It will ask before deleting anything, and it will tell you when a choice matters — such as whether traffic should pass through Cloudflare or go straight to your server.

The only thing it cannot do for you is the one-time account connection: you tick three boxes on Cloudflare's website and paste the result into a file. That is deliberate — it means your token never passes through a chat window. The agent walks you through it and does everything after.

The commands below are for people who would rather drive themselves.

## The setup problem this solves

Cloudflare has no "grant everything" control. Building a token by hand means choosing from **392 separate permissions** across four scopes, and picking wrong produces an error that means nothing to a beginner. Cloudflare does, however, let a token that can manage tokens create other tokens.

So the flow is: the user ticks **three** checkboxes to make a temporary token, pastes it into a file, and the script builds the real one — then deletes the temporary one. Two minutes, no jargon.

**The token is never typed into the conversation.** The script writes an empty file and names it; the user pastes the value in themselves. Storage and handling come from [`toolkit-credentials`](../toolkit-credentials).

## Requirements

**Node 18 or newer.** If you do not have it, the skill installs it for you — the agent runs this, or you can:

```bash
sh scripts/setup-deps.sh --check    # is everything present?
sh scripts/setup-deps.sh            # show the install command, ask, then run it
```

```powershell
.\scripts\setup-deps.ps1            # Windows
```

It picks the right command for your machine (Homebrew, apt, dnf, pacman, zypper, apk, winget) and never installs anything without asking. Where there is no package manager it prints instructions you can follow yourself, including one that needs no admin rights.

Publishing a site to Pages also uses [`wrangler`](https://developers.cloudflare.com/workers/wrangler/), but there is nothing to install — it is fetched on demand through `npx`, which ships with Node, and receives the saved token so it needs no login of its own.

## Setup

```bash
node scripts/setup.mjs begin      # prints the three permissions to tick, and where to paste
node scripts/setup.mjs finish     # builds the real token, deletes the temporary one
node scripts/setup.mjs status     # which account is connected
```

`begin --force` replaces an existing credential. Running `begin` when already connected does nothing.

## If you prefer the command line

```bash
node scripts/cf.mjs whoami
node scripts/cf.mjs zones
node scripts/cf.mjs dns example.com
node scripts/cf.mjs dns-add app.example.com A 203.0.113.10
node scripts/cf.mjs dns-add www.example.com CNAME my-site.pages.dev --proxied
node scripts/cf.mjs dns-remove old.example.com --type A --yes
node scripts/cf.mjs check app.example.com
node scripts/cf.mjs r2

node scripts/cf.mjs pages
node scripts/cf.mjs pages-create my-site
node scripts/cf.mjs pages-deploy my-site ./dist
node scripts/cf.mjs pages-domain my-site www.example.com
node scripts/cf.mjs pages-domains my-site
```

`dns-remove` lists what it matched and refuses to delete without `--yes`.

`check` queries public resolvers through Node's own DNS client, so it reports what a visitor would see — and works on Windows, where `dig` is not installed.

## Example

```
$ node scripts/cf.mjs dns-add status.example.com A 203.0.113.10
added A status.example.com -> 203.0.113.10 (dns-only)
id: 7c1e0a3f9b2d4e5a8f6c1b0d9e2a3f4b

$ node scripts/cf.mjs check status.example.com
A      203.0.113.10
```

## Publishing a site

The whole path, verified end to end — a new project was live on its own hostname over HTTPS about a minute after the domain was attached:

```bash
npm run build                                            # your build, whatever it is
node scripts/cf.mjs pages-create my-site
node scripts/cf.mjs pages-deploy my-site ./dist
node scripts/cf.mjs pages-domain my-site www.example.com
node scripts/cf.mjs pages-domains my-site                # certificate status
```

Re-deploying later is only the third line. Or say *"publish this site to Cloudflare and put www.example.com on it"* and the agent does all of it.

`pages-deploy` runs `wrangler` through `npx` — nothing to install, no second login, the saved token is handed to it. `pages-domain` attaches the domain **and** creates the DNS record, because doing only one leaves it stuck at "pending" forever.

## What it cannot do

Deploying a **Worker** from a local directory still needs `wrangler` run by hand — the same reason Pages did, minus the wrapper. Everything else works here.

Building is yours: `pages-deploy` uploads a directory that already exists.

The token also cannot create further tokens: Cloudflare refuses to grant token-management permission to a token created by another token. Rotate with `begin --force`.

## Playbooks

[`references/playbooks.md`](references/playbooks.md) — pointing a subdomain at a server and waiting for its certificate, replacing a record without downtime, Pages with a custom domain, R2 with a public hostname, and a diagnostic order for "it is not resolving".

## Install

Claude Code:

```
/plugin marketplace add itqanlab/agent-toolkit
/plugin install cloudflare-ops@itqan
```

Any other agent:

```bash
./scripts/install.sh cloudflare-ops
```
