# cloudflare-ops

Connect a Cloudflare account once, then let the agent manage DNS, subdomains, Pages and R2 — without opening the dashboard again.

## The setup problem this solves

Cloudflare has no "grant everything" control. Building a token by hand means choosing from **392 separate permissions** across four scopes, and picking wrong produces an error that means nothing to a beginner. Cloudflare does, however, let a token that can manage tokens create other tokens.

So the flow is: the user ticks **three** checkboxes to make a temporary token, pastes it into a file, and the script builds the real one — then deletes the temporary one. Two minutes, no jargon.

**The token is never typed into the conversation.** The script writes an empty file and names it; the user pastes the value in themselves. Storage and handling come from [`toolkit-credentials`](../toolkit-credentials).

## Requirements

Node 18 or newer. Nothing else. Deploying files to Pages or Workers additionally needs [`wrangler`](https://developers.cloudflare.com/workers/wrangler/), for the reason explained below.

## Setup

```bash
node scripts/setup.mjs begin      # prints the three permissions to tick, and where to paste
node scripts/setup.mjs finish     # builds the real token, deletes the temporary one
node scripts/setup.mjs status     # which account is connected
```

`begin --force` replaces an existing credential. Running `begin` when already connected does nothing.

## Usage

```bash
node scripts/cf.mjs whoami
node scripts/cf.mjs zones
node scripts/cf.mjs dns example.com
node scripts/cf.mjs dns-add app.example.com A 203.0.113.10
node scripts/cf.mjs dns-add www.example.com CNAME my-site.pages.dev --proxied
node scripts/cf.mjs dns-remove old.example.com --type A --yes
node scripts/cf.mjs check app.example.com
node scripts/cf.mjs pages
node scripts/cf.mjs r2
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

## What it cannot do

Uploading files is outside this API surface. Deploying a built site to Pages, or a Worker from a local directory, needs `wrangler` — it reads the same `CLOUDFLARE_API_TOKEN`, so no second setup. Creating the project, attaching custom domains, and every other configuration change works here.

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
