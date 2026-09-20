# Cloudflare playbooks

Sequences that take more than one command, including the steps that are not Cloudflare API calls. Every command is run from the skill directory.

---

## Point a subdomain at a server

The common case: a new app is running on a server, and it needs a hostname.

```
node scripts/cf.mjs dns app.example.com                 # 1. see what exists already
node scripts/cf.mjs dns-add app.example.com A 203.0.113.10
node scripts/cf.mjs check app.example.com               # 2. confirm the world sees it
```

Decisions worth getting right:

**Proxied or DNS-only.** Leave it DNS-only (the default) when the server obtains its own certificate — anything behind a reverse proxy that uses automatic certificate issuance, for example. The certificate authority must reach the origin directly to validate the domain, and proxying blocks that. Add `--proxied` only when Cloudflare should terminate TLS and hide the origin address.

**Propagation.** `check` asks public resolvers, not Cloudflare, so it reflects what a visitor would get. A new record usually appears within a minute. If it does not, the cause is almost always one of: the record was added to a different zone than expected, an old record still exists with the same name, or the domain is not using Cloudflare's nameservers at all — `node scripts/cf.mjs zones` shows whether the zone is `active`.

**Certificates.** If the server issues its own certificate, it will do so on the first request after the record resolves. Wait for `check` to return the right address before testing over HTTPS, or the attempt will fail and the server may back off before retrying.

---

## Replace a record, no downtime

Lower the time-to-live first, wait for the old value to expire, then change it. Resolvers cache the old answer for as long as the previous TTL allowed, so changing the address without this step means some visitors keep reaching the old server.

```
node scripts/cf.mjs dns example.com                     # note the current TTL
node scripts/cf.mjs dns-add www.example.com A <old-address> --ttl 60
# wait out the previous TTL, then point it at the new address
node scripts/cf.mjs dns-remove www.example.com --type A --yes
node scripts/cf.mjs dns-add www.example.com A <new-address> --ttl 60
node scripts/cf.mjs check www.example.com
```

Raise the TTL again once the new address is confirmed and stable.

---

## Deploy a Pages site with a custom domain

Four commands, start to finish. Verified end to end: a new project was live on its own hostname over HTTPS about a minute after the domain was attached.

```bash
npm run build                                            # 1. whatever this project's build is

node scripts/cf.mjs pages-create my-site                 # 2. once per project
node scripts/cf.mjs pages-deploy my-site ./dist          # 3. upload the built files
node scripts/cf.mjs pages-domain my-site www.example.com # 4. domain + DNS together
node scripts/cf.mjs pages-domains my-site                # watch the certificate
```

Re-deploying later is only step 3.

**`pages-deploy` is the one command that shells out.** The files are on this machine and the API cannot reach them, so it runs Cloudflare's own tool through `npx` — nothing to install — and passes the saved credential in the environment, so there is no separate login. The first run downloads the tool, so it needs network access and takes a little longer.

**`pages-domain` deliberately does two things**: attaches the domain to the project and creates the DNS record. Doing only one is the classic failure — the domain sits at "pending" indefinitely, because Cloudflare is waiting for a record that was never created. It also replaces any existing record for that hostname, so pointing an already-used subdomain at a Pages site works without a manual cleanup step.

The record is always proxied. This is one of the few places where that is not a choice: Cloudflare has to be in the request path to serve the site and issue its certificate.

Certificate status moves `initializing` → `pending` → `active`. Expect a minute or two, during which the hostname may return a 52x error — that is the certificate not being ready, not a broken deploy. `pages-domains` shows the current state.

For the apex (`example.com`, no subdomain) pass it the same way. Cloudflare resolves apex CNAMEs correctly where ordinary DNS would not permit the record at all.

---

## Deploy a Worker on your own domain

Verified end to end: uploaded, hostname attached, answering over HTTPS about twenty seconds later.

```bash
node scripts/cf.mjs worker-deploy ./my-worker
node scripts/cf.mjs worker-domain my-worker api.example.com
node scripts/cf.mjs workers                              # confirm the hostname
```

The directory needs a `wrangler.toml` naming the Worker and its entry file:

```toml
name = "my-worker"
main = "src/index.js"
compatibility_date = "2026-08-01"
workers_dev = false
```

**`workers_dev = false` matters more than it looks.** On an account that has never used Workers there is no `workers.dev` subdomain, and a deploy without that line tries to register one named after the current directory — which usually fails, with an error whose only advice is to open the dashboard. Setting it says "this Worker lives on my own domain", and the problem disappears. `worker-deploy` checks for this before running and explains it rather than letting wrangler fail.

**Do not add a DNS record for a Worker hostname.** This is the opposite of Pages: `worker-domain` is the whole job, and Cloudflare creates and manages the record itself. Adding one by hand fights with it.

Immediately after attaching, the hostname may answer `error code: 1104` while the route reaches the edge. That is normal and clears within a minute — it is not a broken deploy.

---

## Create an R2 bucket

```
node scripts/cf.mjs r2                                  # what exists already
```

Creating a bucket is a direct API call. The pattern for anything without a dedicated command:

```js
import { request, whoami } from './scripts/cf.mjs';

const { accounts } = await whoami();
await request(`/accounts/${accounts[0].id}/r2/buckets`, {
  method: 'POST',
  body: { name: 'my-bucket', locationHint: 'weur' },
});
```

To serve a bucket over a custom hostname, connect the domain to the bucket in the R2 settings, then add the DNS record it asks for. Objects are not public until that is done — a bucket alone is private storage.

---

## Work out why a hostname is not resolving

In order, because each step rules out the one below it:

```
node scripts/cf.mjs zones                # is the domain on this account, and active?
node scripts/cf.mjs dns example.com      # does the record exist, spelled correctly?
node scripts/cf.mjs check app.example.com # what do public resolvers actually return?
```

- Zone missing, or not `active` — the domain has not been added to Cloudflare, or its nameservers still point at the previous provider. Nothing else can work until that is fixed, and it is changed at the registrar, not here.
- Record exists but `check` returns nothing — usually seconds-old, so try again. If it persists, look for a second record with the same name shadowing it.
- `check` returns an address you do not recognise — an old record is still present. `dns <domain>` lists every record; look for duplicates of the same name.
- Right address, but the site does not load — DNS is doing its job and the problem is on the server or in its certificate. Stop looking here.

---

## Anything else

Every Cloudflare endpoint is reachable with the same helper:

```js
import { request, requestAll, findZone } from './scripts/cf.mjs';

const zone = await findZone('app.example.com');       // hostname to zone
const rules = await requestAll(`/zones/${zone.id}/rulesets`);
```

`request` throws with a readable message on failure, `requestAll` follows pagination, and both use the saved credential. Do not read the credential directly.
