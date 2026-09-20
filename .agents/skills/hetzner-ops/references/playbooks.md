# Hetzner Cloud playbooks

Sequences that take more than one command, including the parts that are not Hetzner API calls. Every command is run from the skill directory. Add `--project <name>` to any of them to work on a project other than the default.

---

## Set up a new server properly

The order matters. The key goes first, because a server created without one accepts password logins from the moment it boots.

```
node scripts/hz.mjs ssh-keys                                  # 1. is there a key already?
node scripts/hz.mjs ssh-key-add my-laptop ~/.ssh/id_ed25519.pub
node scripts/hz.mjs types --location hel1                     # 2. what fits, and what it costs
node scripts/hz.mjs create web-01 --type cx22 --location hel1 --ssh-key my-laptop
node scripts/hz.mjs server web-01                             # 3. address and state
```

Then, from the user's own machine: `ssh root@<address>`.

**On choosing a size.** `cx` and `cpx` are shared vCPU and are right for almost everything; `ccx` is dedicated and several times the price, worth it only for sustained full-load work. Arm types (`cax`) are cheaper for the same memory but only run software built for arm — a safe default is x86 unless the user knows otherwise.

**On choosing a location.** Pick the one nearest the people who will use it. Prices differ slightly between locations, and not every type exists everywhere, which is why `types` takes a location.

**If there is no SSH key at all.** Create one first with `ssh-keygen -t ed25519`, then upload the `.pub` half. Never upload the other file. `ssh-key-add` refuses if handed a private key, but it is worth saying out loud.

---

## Point a domain at a server

Two cases, and they are different jobs.

**The zone is at Hetzner:**

```
node scripts/hz.mjs zones                                     # is the domain here?
node scripts/hz.mjs server web-01                             # the address to point at
node scripts/hz.mjs dns-add app.example.com A 203.0.113.10
node scripts/hz.mjs check app.example.com                     # what the world sees
```

**The zone is somewhere else** — this skill is the wrong tool for the record. Get the address with `server <name>` and create the record wherever the domain's nameservers actually point.

A zone only works once the registrar has been told to use Hetzner's nameservers. `zones` shows the status; until it is right, records here change nothing that anyone can see.

`dns-add` replaces the existing record set for that name and type. Pass `--append` to add a second address rather than replacing the first — for a second mail server, say.

---

## Resize a server

```
node scripts/hz.mjs server web-01                             # what it is now
node scripts/hz.mjs types --location hel1                     # what it could be
node scripts/hz.mjs resize web-01 cx32                        # prints the consequences, does nothing
node scripts/hz.mjs resize web-01 cx32 --yes                  # goes ahead
```

The server is shut down, changed, and started again — a minute or two offline. The command does all three and waits for each.

**Leave the disk alone unless more disk is the point.** `--upgrade-disk` grows it permanently, and after that the server can never move to a smaller type. Without the flag the change is fully reversible: resize up for a busy week, back down afterwards.

Moving to a **smaller** type only works if the current disk still fits the smaller type — which is exactly what `--upgrade-disk` breaks.

---

## Work out what a project is costing

```
node scripts/hz.mjs costs
```

The usual surprises, in the order they usually turn out to be the answer:

- **A stopped server.** Billing is for existing, not running. Stopping saves nothing.
- **Unassigned IP addresses.** A primary IP left behind after a server is deleted keeps costing money.
- **Volumes.** They outlive the server they were attached to, on purpose, and keep billing.
- **Snapshots.** Charged per gigabyte per month, and easy to forget.

`snapshots` and `volumes` list the last two. Deleting a server does not delete either.

---

## Take a snapshot before something risky

Snapshots are the cheapest insurance before an upgrade. There is no wrapped command, so this is the pattern for anything not covered:

```js
import { request, waitForAction, findServer } from './scripts/hz.mjs';

const server = await findServer('web-01');
const { action, image } = await request(`/servers/${server.id}/actions/create_image`, {
  method: 'POST',
  body: { type: 'snapshot', description: `before the upgrade, ${new Date().toISOString().slice(0, 10)}` },
});
await waitForAction(action, { label: 'taking the snapshot' });
console.log(`snapshot ${image.id} is ready`);
```

Restoring one is `rebuild` with that image id, and it **destroys everything on the server's disk** — confirm explicitly before running it. Look up the exact body first:

```
node scripts/api.mjs show "/servers/{id}/actions/rebuild" post
```

---

## Move a server between sizes, addresses or projects

Hetzner cannot move a server between projects. What can be moved is a snapshot: take one, and Hetzner support can transfer the image, or rebuild a new server from it in the other project. Anyone expecting a one-command move should be told this early.

Within a project, an address can be detached and reattached — a floating or primary IP is how a replacement server takes over the old one's address with no DNS change at all:

```
node scripts/api.mjs search primary ip assign
```

---

## Work out why a server is unreachable

In order, because each step rules out the one below it:

```
node scripts/hz.mjs server web-01          # is it running at all?
node scripts/hz.mjs firewalls              # is the port allowed in?
node scripts/hz.mjs metrics web-01         # is it alive but overloaded?
node scripts/hz.mjs check app.example.com  # is the name pointing at the right address?
```

- **Status is `off`** — start it. If it stopped by itself, something inside it crashed the machine; the console in the Hetzner dashboard shows the boot output.
- **Running, but nothing answers** — check the firewall first. A Hetzner firewall blocks traffic before it ever reaches the server, so nothing on the server can explain it.
- **Firewall is open, still nothing** — the problem is inside the machine and this skill cannot see it. That is a shell session, not an API call.
- **CPU at its ceiling for hours** — it is not down, it is saturated. `resize` is the answer, or fixing whatever is spinning.
- **Name resolves to a different address** — DNS is pointing somewhere else entirely. Fix the record, not the server.

---

## Anything else

Every Hetzner endpoint is reachable with the same helpers:

```js
import { request, requestAll, waitForAction, findServer, findZone } from './scripts/hz.mjs';

const servers = await requestAll('/servers', 'servers');   // follows pagination
const zone = await findZone('app.example.com');            // hostname to zone
```

`request` throws with a readable message on failure, `requestAll` takes the name of the array in the response, and both use the token for whichever project is selected. Do not read the credential directly.

**Anything under `/actions/` returns a job, not a result.** Pass it to `waitForAction` before telling anyone it worked.
