# Dokploy playbooks

Sequences that take more than one command, including the parts that are not Dokploy calls. Every command is run from the skill directory. Add `--instance <name>` to any of them to work on an installation other than the default.

---

## Ship a change

```
node scripts/dk.mjs service web              # 1. what is live now, and from which branch
node scripts/dk.mjs deploy web               # 2. deploy, and stay with it to the end
node scripts/dk.mjs logs web --tail 50       # 3. is it healthy now it is up
```

`deploy` waits. The call itself returns as soon as the build is queued, which is why a script that stops there can report success over a build that is about to fail.

**If the service deploys automatically on push**, `service <name>` says so, and a manual deploy is usually the wrong move — it deploys the same commit again. Check whether the push has landed first.

**Deploy or redeploy.** `deploy` builds the current commit, using the cache. `redeploy` rebuilds from scratch. Reach for `redeploy` when a build succeeded but shipped something stale — an old asset, a dependency that did not update — which is a caching problem, not a code one.

---

## A deploy failed

In order:

```
node scripts/dk.mjs deployments web          # 1. did it fail, or was it never tried?
node scripts/dk.mjs build-log web            # 2. what the build actually said
node scripts/dk.mjs logs web                 # 3. only if the build passed and the app is crashing
```

The distinction in step 2 versus 3 matters and is where most time gets wasted:

- **The build failed** — the code never ran. The answer is in `build-log`: a compile error, a missing dependency, a failed install. Nothing in the application log will mention it, because there is no application.
- **The build passed and the container will not stay up** — `logs` has it. Usually a missing environment variable, or a port the app is not listening on.
- **Both look fine but the site does not load** — the problem is the domain or the certificate, not the deploy. See below.

Read the log and say what broke. Handing back four hundred lines is not an answer.

---

## Put a domain on a service

```
node scripts/dk.mjs domains web              # what it answers on now
```

Adding one is a direct call — the pattern for anything not wrapped:

```js
import { request, findService } from './scripts/dk.mjs';

const service = await findService('web');
await request('domain.create', {
  method: 'POST',
  body: { host: 'app.example.com', applicationId: service.id, port: 3000, https: true, certificateType: 'letsencrypt' },
});
```

Look up the exact fields first — versions differ:

```
node scripts/api.mjs show /domain.create post
```

**The DNS record is not Dokploy's job.** A domain added here does nothing until an A record points at the server's address, and the certificate cannot be issued until that resolves. The usual failure is a domain sitting there with no certificate because the record was never created, or still points somewhere else.

The `port` is the port **inside** the container — what the application listens on, not 80 or 443.

---

## Work out why the site is down

Each step rules out the one below it:

```
node scripts/dk.mjs health                   # is the installation itself healthy?
node scripts/dk.mjs services                 # is this service running, or did its last deploy fail?
node scripts/dk.mjs logs web                 # is it running but erroring?
node scripts/dk.mjs domains web              # is the address even attached to this service?
node scripts/dk.mjs containers               # is the container actually there?
```

- **The installation is unhealthy** — nothing on it can be trusted. Traefik down means every site on the server is down, not just this one.
- **The service says FAILED** — the last deploy did not finish. The previous version may still be serving, which is why the site can look fine while the deploy is broken. `build-log` says why.
- **Running, logs full of errors** — the application is up and unhappy. Usually a missing environment variable or a dependency it cannot reach. `env <name>` lists what it has, by name.
- **A dependency is down** — a database is a service here too. Check it in `services` before blaming the app.
- **Everything looks right** — then it is DNS or the certificate, outside Dokploy entirely. Check what the domain resolves to.

---

## Change an environment variable

```
node scripts/dk.mjs env web                  # names and lengths, never values
```

Setting one replaces the whole block, so it has to be read, edited and written back — and a mistake here empties an application's configuration:

```js
import { request, findService } from './scripts/dk.mjs';

const service = await findService('web');
const app = await request('application.one', { query: { applicationId: service.id } });

const lines = String(app.env || '').split('\n').filter((l) => !l.startsWith('FEATURE_X='));
lines.push('FEATURE_X=true');

await request('application.saveEnvironment', {
  method: 'POST',
  body: {
    applicationId: service.id,
    env: lines.join('\n'),
    buildArgs: app.buildArgs,
    buildSecrets: app.buildSecrets,
    createEnvFile: app.createEnvFile,
  },
});
```

Pass the other fields back as they were. Omitting them is how a build argument disappears without anyone noticing until the next deploy.

**A saved variable is not a live variable.** The container keeps the values it started with, so the change takes effect on the next `deploy` — or `restart` for a running container to pick up a runtime-read value. Say which one is needed.

**Never print the values into a conversation.** If the user needs to see a secret, tell them where to look in the dashboard.

---

## Move something between installations

There is no export. What transfers is the definition, not the deployment: note the repository, branch, build settings, domains and environment variable **names** from the source, and create the service again on the target.

```
node scripts/dk.mjs service web                        # the source
node scripts/dk.mjs --instance other services          # what is already on the target
```

Secrets have to be re-entered by the user on the target. Do not read them from one instance and write them to another through the conversation — that puts every one of them in the transcript. Point at the dashboard for that step.

---

## Anything else

Every Dokploy call is reachable with the same helpers:

```js
import { request, allServices, findService } from './scripts/dk.mjs';

const services = await allServices();                  // everything, flattened
const service = await findService('web');              // name to id, with a clear error if ambiguous
await request('project.all');                          // GET
await request('application.stop', { method: 'POST', body: { applicationId: service.id } });
```

`request` throws with a readable message, and both use the key for whichever installation is selected. Do not read the credential directly.

**Find the call before writing it** — `node scripts/api.mjs search <words>` reads the description from the installation itself, so it describes the version actually running rather than whatever is current upstream.
