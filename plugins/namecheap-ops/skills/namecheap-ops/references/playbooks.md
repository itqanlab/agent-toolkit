# Namecheap playbooks

Sequences that take more than one command, including the parts that are not Namecheap API calls. Every command is run from the skill directory. Add `--account <name>` to any `nc.mjs` command to work on an account other than the default.

---

## See what needs attention

```
node scripts/nc.mjs domains --expiring 90     # what runs out soon, and which of those will not renew
node scripts/nc.mjs balance                   # can it pay for the renewals?
node scripts/nc.mjs price com                 # what one renewal costs
```

A domain with auto-renew off and an expiry inside 60 days is the one to raise first. A domain that lapses goes through a grace period and then a redemption period, and getting it back after that costs a lot more than renewing it. Renewing is done in the Namecheap dashboard, or with `call namecheap.domains.renew ... --yes` once the person has agreed to the cost.

---

## Point a domain at Cloudflare (or any other DNS host)

The order matters. If the new nameservers do not hold the records yet, the site and its email go dark the moment the change lands.

```
node scripts/nc.mjs domain example.com                       # 1. where does it point now?
```

2. Add the domain at the new DNS host and recreate every record there. Compare against `nc.mjs dns example.com` if the domain uses Namecheap's DNS today, because that is the only place the old records can be read from this skill.
3. Copy the two nameservers the new host gave. Then:

```
node scripts/nc.mjs nameservers-set example.com <ns1> <ns2>          # shows the change, does nothing
node scripts/nc.mjs nameservers-set example.com <ns1> <ns2> --yes    # after an explicit yes
node scripts/nc.mjs nameservers example.com                          # confirm Namecheap holds it
```

Namecheap holds the change at once. Resolvers around the world can take up to a day to follow, so do not judge it by the first few minutes.

---

## Point a name at a server, when the domain uses Namecheap's DNS

```
node scripts/nc.mjs dns example.com                          # 1. what is there now?
node scripts/nc.mjs dns-add app.example.com A 203.0.113.9    # 2. the plan, nothing changed
node scripts/nc.mjs dns-add app.example.com A 203.0.113.9 --yes
node scripts/nc.mjs dns example.com                          # 3. read it back
```

If step 1 says the domain does not use Namecheap's DNS, stop. The records belong to whoever runs its nameservers, and `nameservers example.com` says who.

`dns-add` replaces an existing record of the same name and type. For records where several are normal, add `--append`: `dns-add example.com MX mx2.example.net --priority 20 --append --yes`.

---

## Check a name before buying it

```
node scripts/nc.mjs check mybrand.com mybrand.io mybrand.app
node scripts/nc.mjs price com io app
```

`check` says free or taken and marks premium names. Registering is not wrapped here on purpose; it spends money. Send the person to the dashboard, or agree the exact cost first and use `call`.

---

## Work out why a refused request happened

The commonest failure is the address whitelist, and the message names the address Namecheap saw.

1. Is it the address of this machine, or of the relay? The message says which.
2. If it is this machine's and it keeps changing, use a relay: `node scripts/setup.mjs relay <name> "-i ~/.ssh/key user@host"`, then add that server's address to the whitelist once.
3. If the address is already on the whitelist, check that API access is still switched on. Namecheap answers a wrong key and a switched-off account with the same error, `1011102`.
4. If a relay is set and it fails before reaching Namecheap, test it alone: `ssh -i ~/.ssh/key user@host true` must return with no password prompt.

---

## Anything else

`node scripts/nc.mjs call <namecheap.command.name> Key=value ...` reaches every Namecheap command with the saved credentials. Look up the command's parameters in Namecheap's API documentation first, and do not guess at anything that spends money.
