# namecheap-ops

Connect your Namecheap account once, then let the agent run the domains — without opening the dashboard.

## Just ask

You do not need to run anything. Once the skill is installed, say what you want in your own words and the agent does it:

> *"connect my Namecheap account"*
> *"which of my domains expire soon, and will they renew on their own?"*
> *"is mybrand.com free? what would it cost?"*
> *"point example.com at Cloudflare"*
> *"where does this domain's DNS actually live?"*
> *"add app.example.com pointing at my server"*

The agent runs the commands and tells you in plain words what happened. It shows you exactly what will change first, asks before changing it, and always says which account it is working in.

There are two things it cannot do for you, and both are on Namecheap's side: switch API access on, and add an address to Namecheap's whitelist. The agent walks you through both. You also paste the API key into a file yourself, so it never passes through a chat window.

## Namecheap does not have tokens

Other providers give you a token. Namecheap gives you an API key, and then **refuses every request that does not come from an address on a list you keep in its dashboard**. Nothing in the API can edit that list.

That is fine on a fixed connection. On home or mobile internet your address changes, and the list needs editing each time. So the skill has a second route: send the requests **through a server** you can `ssh` into. Namecheap then sees the server's address, which never changes, and you edit the list once.

```bash
node scripts/setup.mjs add mycompany --relay "-i ~/.ssh/id_ed25519 user@203.0.113.5"
```

## Already have the key somewhere?

If the key is in a `.env` file for some script, or in a tool server's configuration, adopt it instead of making another:

```bash
node scripts/setup.mjs import                       # tool configurations; changes nothing
node scripts/setup.mjs import --file ./.env         # a file you name; changes nothing
node scripts/setup.mjs import --file ./.env --yes   # adopts it
```

If the old setup was whitelisted for an address other than this machine's, `import` looks for an SSH server already configured for that address and offers it as the relay. The originals stay where they are and keep working.

## Several accounts

Namecheap will not tell you which account a key belongs to, so each one gets a name here, and the name is printed on everything that changes something.

```bash
node scripts/setup.mjs add clientname
node scripts/setup.mjs status                       # every account, and whether Namecheap accepts it from here
node scripts/setup.mjs use clientname               # make one the default
node scripts/nc.mjs --account clientname domains    # or point a single command elsewhere
```

With several accounts and no default, commands refuse to run rather than guess.

## Requirements

- Node 18 or newer. `sh scripts/setup-deps.sh` checks and offers to install it (Windows: `scripts\setup-deps.ps1`).
- A Namecheap account with API access switched on, and the calling address on its whitelist.
- For a relay: `ssh`, and a server you can reach without a password prompt.

## Setup

```bash
node scripts/setup.mjs add <a-name-for-it>
```

It prints the steps, including which address to put on the whitelist. Fill in the two lines it names in the credential file, then:

```bash
node scripts/setup.mjs verify <a-name-for-it>
```

## If you prefer the command line

```bash
node scripts/nc.mjs whoami                       # account, route Namecheap sees, balance
node scripts/nc.mjs domains --expiring 90        # what expires soon, and what will not renew
node scripts/nc.mjs domain example.com           # one in full
node scripts/nc.mjs check mybrand.com            # free or taken
node scripts/nc.mjs price com io                 # registration and renewal, per year
node scripts/nc.mjs nameservers example.com
node scripts/nc.mjs nameservers-set example.com ns1.host.net ns2.host.net --yes
node scripts/nc.mjs dns example.com              # records, when Namecheap holds them
node scripts/nc.mjs dns-add app.example.com A 203.0.113.9 --yes
node scripts/nc.mjs dns-remove app.example.com --type A --yes
```

## Example

```
$ node scripts/nc.mjs domains --expiring 90
account "mycompany" — 1 expiring within 90 days, of 12 domain(s)

example.com      2026-10-04 (14 days)     auto-renew OFF   DNS elsewhere

! 1 expire within 60 days with auto-renew off, so Namecheap will not renew them on its own:
    example.com  (14 days)
```

## Things worth knowing

- **Most domains have no DNS at Namecheap.** If a domain uses Cloudflare or a hosting plan, its records live there, and Namecheap holds none. The DNS commands say so instead of failing mysteriously.
- **Changing records replaces the whole list.** That is how Namecheap's API works: it has no "add a record". So `dns-add` and `dns-remove` read the list, show you every line that will change, send it all back, and read it again to check.
- **Changing nameservers can take a site and its email offline** if the new ones do not already hold the records. The command warns before it does it.
- **A domain with auto-renew off lapses.** `domains` flags these.

## Anything not wrapped

```bash
node scripts/nc.mjs call namecheap.domains.getContacts DomainName=example.com
```

`call` adds the credentials and address itself and prints the answer. Anything that changes something or spends money waits for `--yes`. Sending the DNS write command by hand is refused, because it deletes every record it is not given.

## What it cannot do

It does not register, renew or transfer domains, because those spend money. It cannot edit Namecheap's whitelist. It does not cover Namecheap hosting, email or SSL products.

## What has been checked

Run against a live account through a relay: connecting, listing, domain details, nameservers, availability, prices, balance, and the messages for a refused address and a wrong key. The record-editing logic was tested offline, and **has not yet been run against a real domain**, because the account it was built on keeps all its DNS elsewhere. The nameserver changes have not been run either. Both refuse to act without `--yes` and the DNS one reads its result back.

## Playbooks

[`references/playbooks.md`](references/playbooks.md) has the multi-step jobs: what needs attention, moving a domain to Cloudflare safely, pointing a name at a server, and working out why a request was refused.

## Install

```bash
./scripts/install.sh namecheap-ops --link --force
```
