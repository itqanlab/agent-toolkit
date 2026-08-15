# dokploy-ops

Connect your Dokploy installations once, then let the agent run what is deployed on them — without opening the dashboard again.

## Just ask

You do not need to run anything. Once the skill is installed, say what you want in your own words and the agent does it:

> *"connect my Dokploy"*
> *"what's deployed, and is any of it broken?"*
> *"deploy the website"*
> *"why did that deploy fail?"*
> *"show me the last 50 log lines from the API"*
> *"restart the app"*
> *"what domain is the client site on?"*
> *"is the server healthy?"*

The agent runs the commands, **waits for the build to actually finish**, and tells you in plain words whether it worked — and when it did not, reads the build output and says what broke rather than handing you four hundred lines of log.

The one thing it cannot do for you is the first connection: you make a key in your dashboard and paste it into a file. That is deliberate — it means your key never passes through a chat window.

The commands below are for people who would rather drive themselves.

## Already have a key somewhere?

Most machines that talk to Dokploy do. Adopt it instead of making another:

```bash
node scripts/setup.mjs import          # shows what it found, changes nothing
node scripts/setup.mjs import --yes    # adopts it
```

The originals stay where they are and keep working.

## Several installations

Dokploy is self-hosted, so every installation is separate — its own address, its own key, and usually its own server. Each one gets a name here, and that name is printed on everything that changes something.

```bash
node scripts/setup.mjs add production https://dokploy.example.com
node scripts/setup.mjs verify production
node scripts/setup.mjs use production          # the default for every command
node scripts/dk.mjs --instance staging services
```

With more than one configured and no default chosen, commands stop and ask rather than guessing. A deploy that lands on the wrong server is not fixed by re-running it on the right one.

## Requirements

**Node 18 or newer.** If you do not have it, the skill installs it for you — the agent runs this, or you can:

```bash
sh scripts/setup-deps.sh --check    # is everything present?
sh scripts/setup-deps.sh            # show the install command, ask, then run it
```

```powershell
.\scripts\setup-deps.ps1            # Windows
```

You also need to be able to reach the installation. Some are only published inside a private network or behind a VPN — if the dashboard does not open in your browser, this will not reach it either, and it says so rather than blaming the key.

## Setup

```bash
node scripts/setup.mjs status                  # what is connected, and does it still answer
node scripts/setup.mjs import [--yes]          # adopt keys already on this machine
node scripts/setup.mjs add <name> [url]        # where to click, and where to paste
node scripts/setup.mjs verify <name>           # check it, and report the version it found
node scripts/setup.mjs use <name>
node scripts/setup.mjs rename <old> <new>
node scripts/setup.mjs forget <name> --yes
```

The address wanted is the **dashboard's own** — the page you log in to — not a site it hosts. Paste the wrong one and `verify` says exactly that, rather than a generic failure.

## If you prefer the command line

```bash
node scripts/dk.mjs whoami
node scripts/dk.mjs services
node scripts/dk.mjs projects
node scripts/dk.mjs service web
node scripts/dk.mjs health

node scripts/dk.mjs deploy web
node scripts/dk.mjs redeploy web
node scripts/dk.mjs restart web
node scripts/dk.mjs stop web --yes
node scripts/dk.mjs start web

node scripts/dk.mjs logs web --tail 200
node scripts/dk.mjs logs web --search error
node scripts/dk.mjs deployments web
node scripts/dk.mjs build-log web
node scripts/dk.mjs domains web
node scripts/dk.mjs env web
node scripts/dk.mjs containers

node scripts/api.mjs search backup postgres
node scripts/api.mjs show /domain.create post
```

Names are only unique within an environment. When one matches twice, the command lists both and stops; narrow it with `--in <project>`.

## Example

```
$ node scripts/dk.mjs services
newpassive-web           running         app       newpassive / production
plane                    running         compose   tasks / production
api                      FAILED          app       duck-tv / production
db                       running         postgres  duck-tv / production

1 service failed its last deployment: api

$ node scripts/dk.mjs deployments api
FAILED          12m ago    fix(api): add the migration for lead sources
succeeded       2d ago     chore(deps): bump the runtime
```

## Four things worth knowing

**"Accepted" is not "deployed".** The API answers the moment a build is queued. `deploy` follows it to the end and reports what really happened — a queued build that fails two minutes later is not a success.

**`logs` and `build-log` answer different questions.** `logs` is what the running app is printing; `build-log` is why the build failed. If the build failed, there is no app, and its log will be silent about it.

**`restart` does not pick up new code.** It restarts what is already running. New code is `deploy`. Stale content after a good deploy is `redeploy`, which rebuilds without the cache.

**Environment variables are secrets.** `env` shows names and lengths only. `--values` prints them in full — useful in a terminal nobody is watching, a bad idea anywhere that records.

## Anything not wrapped

Dokploy has around 540 calls and `request()` reaches all of them with the same key. The description comes **from your own installation**, so it matches the version you are actually running rather than whatever is current upstream:

```bash
node scripts/api.mjs search volume backup
node scripts/api.mjs show /backup.create post
```

`findService(name)` is exported because nothing in this API is addressed by name — every call wants an id, and ids appear nowhere in the dashboard.

## What it cannot do

It talks to Dokploy, not to the machine underneath it. Disk space, system packages and anything outside a container need a shell session — pair this with a server skill for that half.

It also does not install Dokploy. The installation has to exist and be reachable first.

## Playbooks

[`references/playbooks.md`](references/playbooks.md) — shipping a change, working out why a deploy failed (and which log answers it), putting a domain on a service, a diagnostic order for "the site is down", changing an environment variable without wiping the rest, and moving a service between installations.

## Install

Claude Code:

```
/plugin marketplace add itqanlab/agent-toolkit
/plugin install dokploy-ops@itqan
```

Any other agent:

```bash
./scripts/install.sh dokploy-ops
```
