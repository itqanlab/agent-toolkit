#!/usr/bin/env node
// setup.mjs — connect one or more Dokploy instances.
//
// Dokploy is self-hosted, so a credential here is two things: the address of the
// installation and a key made inside it. That also means there is no shared
// place to look anything up — an instance that is unreachable is unreachable,
// and saying so clearly is most of this file's job.
//
//   status  — what is connected, and whether it still answers
//   import  — adopt instances already configured on this machine
//   add     — connect one by hand
//   verify  — check a pasted key and remember that it works
//   use     — choose the default instance
//   rename  — give one a better name
//   forget  — remove one from this machine

import { providerPath, recordState, permissionWarnings } from '../lib/store.mjs';
import { listTargets, scaffoldTarget, setDefault, forgetTarget, renameTarget, slug, defaultTargetName } from '../lib/targets.mjs';
import { findExisting } from '../lib/adopt.mjs';
import { SPEC } from './dk.mjs';

// The names other tools use for the same two values.
const ALIASES = {
  url: ['DOKPLOY_URL', 'DOKPLOY_BASE_URL', 'DOKPLOY_HOST'],
  key: ['DOKPLOY_API_KEY', 'DOKPLOY_TOKEN', 'DOKPLOY_KEY'],
};

const normalise = (url) => String(url || '').trim().replace(/\/+$/, '').replace(/\/api$/, '');

/** Check an address and key together, without saving either. */
async function probe(url, key) {
  const base = normalise(url);
  if (!/^https?:\/\//.test(base)) {
    return { ok: false, why: `"${url}" is not a web address. It should start with https:// and be the address of the Dokploy dashboard.` };
  }

  let response;
  try {
    response = await fetch(`${base}/api/project.all`, {
      headers: { 'x-api-key': key, 'User-Agent': 'itqan-agent-toolkit/1.0' },
      signal: AbortSignal.timeout(15000),
    });
  } catch (err) {
    return {
      ok: false,
      why:
        `Could not reach ${base} (${err.message}).\n` +
        '  The address may be wrong, the server may be down, or this machine may not be on a\n' +
        '  network that can see it — some installations are only reachable over a VPN.',
    };
  }

  if (response.status === 401 || response.status === 403) {
    return { ok: false, why: `${base} is reachable, but it did not accept that key.` };
  }
  const text = await response.text();
  if (!response.ok) return { ok: false, why: `${base} answered HTTP ${response.status}.` };

  let projects;
  try {
    projects = JSON.parse(text);
  } catch {
    return { ok: false, why: `${base} answered with a web page rather than data — that address is probably a site Dokploy hosts, not Dokploy itself.` };
  }

  const version = await fetch(`${base}/api/settings.getDokployVersion`, { headers: { 'x-api-key': key } })
    .then((r) => r.json()).catch(() => null);

  const services = (projects || []).flatMap((p) => (p.environments || []).flatMap((e) => [
    ...(e.applications || []), ...(e.compose || []), ...(e.postgres || []), ...(e.mysql || []),
    ...(e.mariadb || []), ...(e.mongo || []), ...(e.redis || []), ...(e.libsql || []),
  ]));

  return { ok: true, projects: (projects || []).length, services: services.length, version };
}

// --- status ------------------------------------------------------------------

async function status() {
  const targets = listTargets(SPEC);
  if (!targets.length) {
    console.log('No Dokploy instance is connected yet.\n');
    const existing = findExisting(ALIASES);
    if (existing.length) {
      console.log(`This machine already has ${existing.length} Dokploy instance(s) configured elsewhere:`);
      for (const e of existing) console.log(`  ${e.source}   ${normalise(e.values.url)}`);
      console.log('\nAdopt them — nothing new to create:\n  node scripts/setup.mjs import');
    } else {
      console.log('Connect one:\n  node scripts/setup.mjs add <a-name-for-it>');
    }
    process.exitCode = 1;
    return;
  }

  const fallback = defaultTargetName(SPEC);
  console.log(`${targets.length} Dokploy instance(s) on this machine\n`);
  for (const target of targets) {
    const mark = slug(fallback || '') === target.slug ? '*' : ' ';
    if (!target.complete) {
      console.log(`${mark} ${target.name.padEnd(16)} ${normalise(target.fields.url) || '(no address)'}   waiting for a key to be pasted in`);
      continue;
    }
    const result = await probe(target.fields.url, target.fields.key);
    const where = normalise(target.fields.url).padEnd(38);
    console.log(`${mark} ${target.name.padEnd(16)} ${where} ${result.ok ? `works — ${result.projects} project(s), ${result.services} service(s)` : 'NOT WORKING'}`);
    if (!result.ok) console.log(`${''.padEnd(19)}${result.why.split('\n')[0]}`);
  }
  console.log('\n* is the default. Any command can be pointed elsewhere with --instance <name>.');
  for (const warning of permissionWarnings()) console.log(`\n! ${warning}`);
}

// --- import ------------------------------------------------------------------

async function importExisting({ yes }) {
  const existing = findExisting(ALIASES);
  if (!existing.length) {
    console.log('No Dokploy configuration found elsewhere on this machine.');
    console.log('Connect one by hand instead:\n  node scripts/setup.mjs add <a-name-for-it>');
    process.exitCode = 1;
    return;
  }

  const known = listTargets(SPEC);
  const plan = existing.map((entry) => {
    const url = normalise(entry.values.url);
    const already = known.find((t) => normalise(t.fields.url) === url);
    // A tool server called "dokploy-mastudio" is the mastudio instance.
    const stripped = entry.suggestedName.replace(/^dokploy[-_]?/i, '');
    // Failing that, the hostname is a better name than nothing: dokploy.example.com → example.
    const fromHost = url.replace(/^https?:\/\//, '').split('.').filter((p) => p !== 'dokploy')[0];
    return { ...entry, url, name: already ? already.name : (stripped || fromHost || 'main'), already: Boolean(already) };
  });

  console.log(`Found ${plan.length} Dokploy instance(s) already configured here:\n`);
  for (const entry of plan) {
    console.log(`  ${entry.source}`);
    console.log(`      ${entry.url}`);
    console.log(`      would be called "${entry.name}"${entry.already ? '   (already connected — will be left alone)' : ''}`);
  }

  if (!yes) {
    console.log('\nNothing has been changed. To adopt them:\n  node scripts/setup.mjs import --yes');
    console.log('\nThe keys are copied into this toolkit\'s own credential file. The originals stay');
    console.log('where they are and keep working.');
    return;
  }

  let added = 0;
  for (const entry of plan) {
    if (entry.already) continue;
    const result = await probe(entry.url, entry.values.key);
    if (!result.ok) {
      console.log(`\n"${entry.name}" was skipped — ${result.why.split('\n')[0]}`);
      continue;
    }
    scaffoldTarget(SPEC, entry.name, { url: entry.url, key: entry.values.key });
    recordState(SPEC.provider, { verified_at: new Date().toISOString() });
    console.log(`\nconnected "${entry.name}" — ${result.projects} project(s), ${result.services} service(s)${result.version ? `, Dokploy ${result.version}` : ''}`);
    added += 1;
  }

  console.log(added ? `\n${added} instance(s) added. See them with:  node scripts/setup.mjs status` : '\nNothing new to add.');
}

// --- add / verify -------------------------------------------------------------

function add(name, address, { force }) {
  if (!name) throw new Error('usage: add <a-name-for-it> [https://dokploy.example.com]');

  const existing = listTargets(SPEC).find((t) => t.slug === slug(name));
  if (existing?.complete && !force) {
    console.log(`"${existing.name}" is already connected (${normalise(existing.fields.url)}). Nothing to do.`);
    console.log('To replace its key, run this again with --force.');
    return;
  }

  const url = address ? normalise(address) : (force ? normalise(existing?.fields.url) : '');
  const { keys } = scaffoldTarget(SPEC, name, { ...(url ? { url } : {}), key: '' });

  console.log(`
Connecting a Dokploy instance called "${name}". This takes about a minute.

Dokploy runs on your own server, so each installation is separate and needs its
own key. If you have several, do this once for each and give them different names.

${url ? `Its address is set to:  ${url}` : `STEP 0 — the address

  This wants the address of the Dokploy dashboard itself — the page you log in
  to, such as https://dokploy.example.com — not the address of a site it hosts.
  Put it after ${keys.url}= in the file named below.`}

STEP 1 — create the key

  1. Open the Dokploy dashboard${url ? `:\n\n       ${url}\n` : ' and sign in.'}
  2. Click your account, bottom left, and open "Settings".

  3. Find the "API/CLI" section on your profile page.
     (Layouts move between versions. It is the only place keys are made, so if
      it is not where this says, look for "API" anywhere under Settings.)

  4. Click "Generate API Key" — or "Create API Key", depending on the version.

  5. Copy the key it shows you. It is shown once.

STEP 2 — paste it in

  Open this file in any text editor:

     ${providerPath(SPEC.provider)}

  Find the line that starts with ${keys.key}= and paste the key straight
  after the "=", with no quotes and no spaces. Save the file.

STEP 3 — tell me you are done

     node scripts/setup.mjs verify ${name}
`);
}

async function verify(name) {
  const targets = listTargets(SPEC);
  const wanted = name
    ? targets.find((t) => t.slug === slug(name))
    : targets.filter((t) => t.complete).pop() || targets[targets.length - 1];

  if (!wanted) {
    throw new Error(name ? `There is no instance called "${name}".` : 'Nothing to verify yet. Run:  node scripts/setup.mjs add <a-name-for-it>');
  }
  if (!wanted.complete) {
    const missing = [!wanted.fields.url && 'its address', !wanted.fields.key && 'its key'].filter(Boolean).join(' and ');
    console.error(
      `"${wanted.name}" is still missing ${missing}.\n\n` +
      `Open this file and fill it in:\n  ${providerPath(SPEC.provider)}`,
    );
    process.exit(1);
  }

  console.log(`Checking "${wanted.name}" at ${normalise(wanted.fields.url)}...`);
  const result = await probe(wanted.fields.url, wanted.fields.key);
  if (!result.ok) {
    console.error(
      `${result.why}\n\n` +
      'If the address is right and the server is up, the key may have been revoked or copied\n' +
      'incompletely. Make a fresh one and paste it again:\n' +
      `  node scripts/setup.mjs add ${wanted.name} --force`,
    );
    process.exit(1);
  }

  recordState(SPEC.provider, { verified_at: new Date().toISOString() });
  console.log(`
Done. The instance "${wanted.name}" is connected.

  address:  ${normalise(wanted.fields.url)}
  version:  ${result.version || '(not reported)'}
  holds:    ${result.projects} project(s), ${result.services} service(s)

Try:  node scripts/dk.mjs services
`);
}

// --- default / rename / removal --------------------------------------------------

function use(name) {
  if (!name) {
    const targets = listTargets(SPEC).filter((t) => t.complete);
    throw new Error(`usage: use <name>\nConfigured: ${targets.map((t) => t.name).join(', ') || '(none)'}`);
  }
  const target = setDefault(SPEC, name);
  console.log(`"${target.name}" is now the default instance for every command.`);
  console.log('Point a single command somewhere else with  --instance <name>.');
}

function rename(from, to) {
  if (!from || !to) throw new Error('usage: rename <current-name> <new-name>');
  const target = renameTarget(SPEC, from, to);
  console.log(`"${from}" is now called "${target.name}".`);
}

function forget(name, { yes }) {
  if (!name) throw new Error('usage: forget <name> --yes');
  const target = listTargets(SPEC).find((t) => t.slug === slug(name));
  if (!target) throw new Error(`There is no instance called "${name}".`);

  if (!yes) {
    console.log(`This removes the saved key for "${target.name}" (${normalise(target.fields.url)}) from this machine.`);
    console.log('Nothing on the server changes, and the key still exists — revoke it in the dashboard');
    console.log('under Settings → API/CLI if it is finished with.');
    console.log(`\nTo go ahead:  node scripts/setup.mjs forget ${target.name} --yes`);
    process.exitCode = 1;
    return;
  }
  forgetTarget(SPEC, name);
  console.log(`Removed "${target.name}" from this machine.`);
}

// --- command line ---------------------------------------------------------------

const [command = 'status', ...rest] = process.argv.slice(2);
const positional = rest.filter((a) => !a.startsWith('--'));
const options = { force: rest.includes('--force'), yes: rest.includes('--yes') };

try {
  if (command === 'status' || command === 'list') await status();
  else if (command === 'import') await importExisting(options);
  else if (command === 'add') add(positional[0], positional[1], options);
  else if (command === 'verify' || command === 'finish') await verify(positional[0]);
  else if (command === 'use') use(positional[0]);
  else if (command === 'rename') rename(positional[0], positional[1]);
  else if (command === 'forget' || command === 'remove') forget(positional[0], options);
  else {
    console.error('usage: setup.mjs <status|import|add|verify|use|rename|forget> [name] [--force] [--yes]');
    process.exit(2);
  }
} catch (err) {
  console.error(`error: ${err.message}`);
  process.exit(1);
}
