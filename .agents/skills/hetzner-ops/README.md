# hetzner-ops

Connect your Hetzner Cloud projects once, then let the agent run the servers — without opening the console again.

## Just ask

You do not need to run anything. Once the skill is installed, say what you want in your own words and the agent does it:

> *"connect my Hetzner account"*
> *"what servers do I have, and what are they costing me?"*
> *"the site is slow — is the server overloaded?"*
> *"reboot web-01"*
> *"make the server bigger"*
> *"create a small server in Helsinki with my SSH key on it"*
> *"add app.mysite.com pointing at that server"*
> *"delete the old staging box"*

The agent runs the commands, waits for each change to actually finish, and tells you in plain words whether it worked. It asks before deleting anything, warns you when a choice cannot be undone, and always says which project it is working in.

The one thing it cannot do for you is the first connection: you make a token on Hetzner's website and paste it into a file. That is deliberate — it means your token never passes through a chat window. The agent walks you through it and does everything after.

The commands below are for people who would rather drive themselves.

## Already have a token somewhere?

Most machines do — in a tool server, or exported in a shell profile. Adopt it instead of making another:

```bash
node scripts/setup.mjs import          # shows what it found, changes nothing
node scripts/setup.mjs import --yes    # adopts it
```

The originals stay where they are and keep working.

## Several projects

A Hetzner token belongs to **one project**, and Hetzner will not tell you which — there is no "who am I" call. So each one gets a name here, and that name is printed on everything that changes something.

```bash
node scripts/setup.mjs add production
node scripts/setup.mjs verify production
node scripts/setup.mjs use production        # the default for every command
node scripts/hz.mjs --project staging servers
```

With more than one configured and no default chosen, commands stop and ask rather than guessing. That is the whole point: the expensive mistake with multiple projects is never "which command", it is "which account did that just run against".

## Requirements

**Node 18 or newer.** If you do not have it, the skill installs it for you — the agent runs this, or you can:

```bash
sh scripts/setup-deps.sh --check    # is everything present?
sh scripts/setup-deps.sh            # show the install command, ask, then run it
```

```powershell
.\scripts\setup-deps.ps1            # Windows
```

It picks the right command for your machine (Homebrew, apt, dnf, pacman, zypper, apk, winget) and never installs anything without asking.

## Setup

```bash
node scripts/setup.mjs status                # what is connected, and does it still work
node scripts/setup.mjs import [--yes]        # adopt tokens already on this machine
node scripts/setup.mjs add <name>            # where to click, and where to paste
node scripts/setup.mjs verify <name>         # check it, and say whether it can make changes
node scripts/setup.mjs use <name>            # choose the default
node scripts/setup.mjs rename <old> <new>
node scripts/setup.mjs forget <name> --yes
```

Hetzner asks **Read** or **Read & Write** when the token is created, and it cannot be changed afterwards. `verify` tells you which one you pasted, so a read-only token is caught at setup rather than halfway through a deployment.

## If you prefer the command line

```bash
node scripts/hz.mjs whoami
node scripts/hz.mjs servers
node scripts/hz.mjs server web-01
node scripts/hz.mjs costs
node scripts/hz.mjs metrics web-01 --hours 24

node scripts/hz.mjs create web-01 --type cx22 --location hel1 --ssh-key my-laptop
node scripts/hz.mjs shutdown web-01
node scripts/hz.mjs power-on web-01
node scripts/hz.mjs reboot web-01
node scripts/hz.mjs resize web-01 cx32 --yes
node scripts/hz.mjs delete old-staging --yes

node scripts/hz.mjs ssh-keys
node scripts/hz.mjs ssh-key-add my-laptop ~/.ssh/id_ed25519.pub
node scripts/hz.mjs firewalls
node scripts/hz.mjs volumes
node scripts/hz.mjs networks
node scripts/hz.mjs types --location hel1
node scripts/hz.mjs locations

node scripts/hz.mjs zones
node scripts/hz.mjs dns example.com
node scripts/hz.mjs dns-add app.example.com A 203.0.113.10
node scripts/hz.mjs check app.example.com

node scripts/api.mjs search firewall rules
node scripts/api.mjs show "/servers/{id}/actions/rebuild" post
```

`delete`, `power-off` and `dns-remove` print what they matched and refuse to act without `--yes`.

## Example

```
$ node scripts/hz.mjs servers
project "production" — 2 servers

web-01                   running    203.0.113.10     cx22     hel1   €4.51/mo
db-01                    running    203.0.113.11     cx32     hel1   €8.98/mo

$ node scripts/hz.mjs costs
server web-01 (cx22)                     €4.51/mo
server db-01 (cx32)                      €8.98/mo
volume db-data (100 GB)                  €5.24/mo
---------------------------------------- ---------
project "production"                     €18.73/mo
```

## Four things worth knowing

**A stopped server still costs money.** Hetzner bills for it existing, not running. Stopping to save money does not. Deleting does.

**`shutdown` is not `power-off`.** The first asks the operating system to stop cleanly. The second cuts the power, and unwritten data is lost. `power-off` will not run without `--yes` and explains the difference first.

**Growing a disk cannot be undone.** A resize with `--upgrade-disk` locks the server out of every smaller type, permanently. Without it, resizing is reversible in both directions.

**Creating a server with no SSH key means password login is on from the first second.** `create` refuses unless you pass `--no-ssh-key` deliberately, and when you do, the root password is written into the credential file rather than printed on screen.

## Anything not wrapped

Hetzner Cloud has about 150 endpoints and `request()` reaches all of them with the same token. The only hard part is knowing which one and what it wants, so the skill looks it up instead of guessing:

```bash
node scripts/api.mjs search load balancer service
node scripts/api.mjs show "/load_balancers/{id}/actions/add_service" post
```

It reads Hetzner's own API description — downloaded once, cached next to the credentials — and resolves the internal references so the request body is readable rather than a pointer.

Anything under `/actions/` returns a job that is still running. `waitForAction` is exported for exactly that, and every wrapped command already uses it.

## What it cannot do

**Hetzner Cloud only.** Dedicated servers, storage boxes and the older Robot service are a separate product with separate credentials.

It also does not touch anything **inside** a server. Creating the machine is where this stops.

## Playbooks

[`references/playbooks.md`](references/playbooks.md) — setting up a server properly (key first), pointing a domain at it, resizing without locking yourself out of smaller sizes, finding out where the money is going, snapshotting before something risky, and a diagnostic order for "the server is unreachable".

## Install

Claude Code:

```
/plugin marketplace add itqanlab/agent-toolkit
/plugin install hetzner-ops@itqan
```

Any other agent:

```bash
./scripts/install.sh hetzner-ops
```
