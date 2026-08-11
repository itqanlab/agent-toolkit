---
name: cloudflare-ops
description: "Connect a Cloudflare account once, then manage DNS records, subdomains, Pages sites, R2 buckets and Workers from the agent without opening the dashboard again. Setup is a two-minute guided flow that needs three checkboxes, not the 390-odd permissions Cloudflare would otherwise ask you to pick by hand. Works on macOS, Windows and Linux. Triggers: 'connect my Cloudflare', 'add a subdomain', 'point a domain at my server', 'create a DNS record', 'set up Cloudflare Pages', 'add a custom domain to Pages', 'create an R2 bucket', 'check if DNS has propagated', 'list my domains', 'cloudflare'."
license: MIT
compatibility: Requires Node 18 or newer — run scripts/setup-deps.sh (or scripts/setup-deps.ps1 on Windows) to check for it and install it if missing. Needs network access to the Cloudflare API. Uploading a built site to Pages, or a Worker from a local directory, additionally needs wrangler; nothing else here does.
metadata:
  author: itqanlab
  version: 1.0.0
---

# Cloudflare

Everything here runs through two scripts. `scripts/setup.mjs` connects an account; `scripts/cf.mjs` does the work.

## Who you are doing this for

Assume the person asking has never opened a terminal. **You run the commands; they never do.** They are asked to do exactly two things by hand, and only because neither can be done for them: tick three boxes on a web page, and paste the resulting value into a file so it never passes through the conversation.

Everything else — checking what exists, adding the record, waiting for it to resolve, confirming it worked — is yours. Report it in plain words. "app.example.com now points at your server, and the world can see it" is the result they asked for; the record id is not.

If they are clearly comfortable with a terminal, stop narrating and let them drive.

## Before anything else: check the dependencies

These scripts need Node 18 or newer. Check first, so a missing dependency does not surface as a confusing failure halfway through a setup:

```
sh scripts/setup-deps.sh --check
```

Non-zero exit means missing or too old. `sh scripts/setup-deps.sh` (Windows: `.\scripts\setup-deps.ps1`) prints the right install command for that machine and asks before running it; `--yes` skips the question. Where there is no package manager it gives instructions the person can follow, including one that needs no admin rights.

## Connect an account first

Every command needs a saved credential. Check before doing anything else:

```
node scripts/setup.mjs status
```

If it reports that Cloudflare is not connected, run the guided setup and follow what it prints:

```
node scripts/setup.mjs begin
```

It writes an empty file, tells the user exactly which three permission rows to tick in the Cloudflare dashboard, and stops. **Never ask for the token in the conversation** — the user pastes it into the file the script names. When they say they are done:

```
node scripts/setup.mjs finish
```

That builds the real credential from the temporary one, saves it, deletes the temporary one, and confirms which account is connected. Re-running `begin` when already connected does nothing; add `--force` to replace a saved credential.

Why two steps: Cloudflare has no "grant everything" control, and a token built by hand means choosing from hundreds of permissions. A token that can manage tokens can create the full one, so the user ticks three boxes and the script does the rest.

The credential that results can do everything **except create more tokens** — Cloudflare refuses to grant that to a token made by another token. Rotating means running `begin --force` and making a fresh temporary token.

## Commands

```
node scripts/cf.mjs whoami                  which account is connected
node scripts/cf.mjs zones                   every domain on the account
node scripts/cf.mjs dns <domain>            all records for a domain
node scripts/cf.mjs dns-add <name> <type> <content> [--proxied] [--ttl 300]
node scripts/cf.mjs dns-remove <name> [--type A] --yes
node scripts/cf.mjs check <hostname>        what public resolvers currently return
node scripts/cf.mjs pages                   Pages projects and their domains
node scripts/cf.mjs r2                      R2 buckets
```

`dns-add` takes the full hostname — `app.example.com`, not `app`. The zone is worked out from it, so nothing needs a zone id.

Anything not covered by a command is a direct API call; `references/playbooks.md` shows the pattern.

## Before changing anything

**Show the current state first.** Run `dns <domain>` and show the user the records that matter before adding or replacing one. A wrong DNS record takes a site off the internet, and the person asking may not know what the existing records do.

**Deleting requires confirmation.** `dns-remove` lists what matches and refuses to act without `--yes`. Show that list to the user and get an explicit yes before re-running with the flag. Never pass `--yes` on the first attempt.

**Proxied or not is a real decision, not a default.** Proxied (orange cloud) routes traffic through Cloudflare, hides the origin address and provides a certificate. DNS-only points straight at the server. A host that terminates its own TLS, or any non-HTTP service, needs DNS-only — proxying it will break it. If it is not obvious which is wanted, ask.

## Playbooks

`references/playbooks.md` has the step-by-step sequences, including the parts that are not Cloudflare API calls:

- point a subdomain at a server, and wait for the certificate
- deploy a Pages site and attach a custom domain
- create an R2 bucket and connect it to a public hostname
- move a domain between servers with no downtime
- work out why a hostname is not resolving

## What this cannot do

Uploading files is outside the API surface used here. Deploying a built site to Pages, or a Worker script from a local directory, needs Cloudflare's own command line tool — `references/playbooks.md` covers where that hand-off happens. Everything that is a configuration change rather than a file upload works through these scripts.

## Failure messages

Errors are rewritten for people who do not know Cloudflare's error codes. A refused call explains that a permission is probably missing and gives the command to fix it; an unrecognised credential says it may have been deleted, and how to replace it. Keep that habit for anything added here: say what happened, then what to do next.
