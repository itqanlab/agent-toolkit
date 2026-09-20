#!/usr/bin/env node
// setup.mjs — connect one or more Hetzner projects.
//
// Hetzner is refreshingly simple compared to providers that make you assemble
// permissions: a token is one form with one choice on it, Read or Read & Write.
// So there is no minting dance here. The whole job is (a) find a token the
// machine already has, or walk the user through making one, and (b) keep several
// of them straight, because a Hetzner token belongs to exactly one project and
// will not tell you which.
//
//   status  — what is connected
//   import  — adopt tokens already configured on this machine
//   add     — connect a project by hand
//   verify  — check a pasted token and remember that it works
//   use     — choose the default project
//   forget  — remove one from this machine

import { providerPath, recordState, permissionWarnings } from '../lib/store.mjs';
import { listTargets, scaffoldTarget, setDefault, forgetTarget, renameTarget, slug, defaultTargetName } from '../lib/targets.mjs';
import { findExisting } from '../lib/adopt.mjs';
import { SPEC } from './hz.mjs';

const CONSOLE = 'https://console.hetzner.cloud/';

// The names other tools use for the same token, most common first.
const ALIASES = { token: ['HETZNER_API_TOKEN', 'HCLOUD_TOKEN', 'HETZNER_TOKEN', 'HETZNER_CLOUD_TOKEN'] };

/**
 * Check a token without saving it. Hetzner has no "who am I" endpoint, so the
 * cheapest honest test is asking for one server: it proves the token is valid
 * and that the project is reachable, and tells us how much is in it.
 */
async function probe(token) {
  const response = await fetch('https://api.hetzner.cloud/v1/servers?per_page=1', {
    headers: { Authorization: `Bearer ${token}`, 'User-Agent': 'itqan-agent-toolkit/1.0' },
  });
  const body = await response.json().catch(() => ({}));
  if (body.error) {
    if (body.error.code === 'unauthorized') return { ok: false, why: 'Hetzner did not accept that token.' };
    return { ok: false, why: body.error.message || body.error.code };
  }
  if (!response.ok) return { ok: false, why: `Hetzner answered HTTP ${response.status}` };
  return { ok: true, servers: body.meta?.pagination?.total_entries ?? (body.servers || []).length };
}

/**
 * Read & Write cannot be detected from a successful read, and finding out the
 * hard way means a failure halfway through someone's first change. Ask Hetzner
 * to do something harmless that a read-only token is not allowed to do.
 */
async function probeWritable(token) {
  const response = await fetch('https://api.hetzner.cloud/v1/ssh_keys', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'User-Agent': 'itqan-agent-toolkit/1.0', 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: '', public_key: '' }),
  });
  const body = await response.json().catch(() => ({}));
  // A read-only token is refused before the empty fields are ever looked at.
  return body.error?.code !== 'forbidden';
}

// --- status ------------------------------------------------------------------

async function status() {
  const targets = listTargets(SPEC);
  if (!targets.length) {
    console.log('No Hetzner project is connected yet.\n');
    const existing = findExisting(ALIASES);
    if (existing.length) {
      console.log(`This machine already has ${existing.length} Hetzner token(s) configured elsewhere:`);
      for (const e of existing) console.log(`  ${e.source}`);
      console.log('\nAdopt them — nothing new to create:\n  node scripts/setup.mjs import');
    } else {
      console.log('Connect one:\n  node scripts/setup.mjs add <a-name-for-it>');
    }
    process.exitCode = 1;
    return;
  }

  const fallback = defaultTargetName(SPEC);
  console.log(`${targets.length} Hetzner project(s) on this machine\n`);
  for (const target of targets) {
    const mark = slug(fallback || '') === target.slug ? '*' : ' ';
    if (!target.complete) {
      console.log(`${mark} ${target.name.padEnd(20)} waiting for a token to be pasted in`);
      continue;
    }
    const result = await probe(target.fields.token);
    console.log(`${mark} ${target.name.padEnd(20)} ${result.ok ? `works — ${result.servers} server(s)` : `NOT WORKING — ${result.why}`}`);
  }
  console.log('\n* is the default. Any command can be pointed elsewhere with --project <name>.');
  for (const warning of permissionWarnings()) console.log(`\n! ${warning}`);
}

// --- import ------------------------------------------------------------------

async function importExisting({ yes }) {
  const existing = findExisting(ALIASES);
  if (!existing.length) {
    console.log('No Hetzner token found in the tool configurations on this machine.');
    console.log('Connect one by hand instead:\n  node scripts/setup.mjs add <a-name-for-it>');
    process.exitCode = 1;
    return;
  }

  const known = listTargets(SPEC);
  const plan = existing.map((entry) => {
    const already = known.find((t) => t.fields.token && t.fields.token === entry.values.token);
    // "hetzner-7lmna" is a server name; "7lmna" is what the project is called.
    const name = entry.suggestedName.replace(/^(hetzner|hcloud)[-_]?/i, '') || entry.suggestedName;
    return { ...entry, name: already ? already.name : name, already: Boolean(already) };
  });

  console.log(`Found ${plan.length} Hetzner token(s) already configured here:\n`);
  for (const entry of plan) {
    console.log(`  ${entry.source}`);
    console.log(`      would be called "${entry.name}"${entry.already ? '   (already connected — will be left alone)' : ''}`);
  }

  if (!yes) {
    console.log('\nNothing has been changed. To adopt them:\n  node scripts/setup.mjs import --yes');
    console.log('\nThe tokens are copied into this toolkit\'s own credential file. The originals stay');
    console.log('where they are and keep working.');
    return;
  }

  let added = 0;
  for (const entry of plan) {
    if (entry.already) continue;
    const result = await probe(entry.values.token);
    if (!result.ok) {
      console.log(`\n"${entry.name}" was skipped — ${result.why}`);
      continue;
    }
    scaffoldTarget(SPEC, entry.name, { token: entry.values.token });
    recordState(SPEC.provider, { verified_at: new Date().toISOString() });
    console.log(`\nconnected "${entry.name}" — ${result.servers} server(s)${(await probeWritable(entry.values.token)) ? '' : '   (read-only token: it can look, not change)'}`);
    added += 1;
  }

  console.log(added ? `\n${added} project(s) added. See them with:  node scripts/setup.mjs status` : '\nNothing new to add.');
}

// --- add / verify -------------------------------------------------------------

function add(name, { force }) {
  if (!name) throw new Error('usage: add <a-name-for-it>   e.g. add production');

  const existing = listTargets(SPEC).find((t) => t.slug === slug(name));
  if (existing?.complete && !force) {
    console.log(`"${existing.name}" is already connected. Nothing to do.`);
    console.log('To replace its token, run this again with --force.');
    return;
  }

  const { keys } = scaffoldTarget(SPEC, name, force ? { token: '' } : {});

  console.log(`
Connecting a Hetzner project called "${name}". This takes about a minute.

A Hetzner token belongs to ONE project. If you have several projects, do this
once per project and give each a different name here.

STEP 1 — create the token

  1. Open this page and sign in:

       ${CONSOLE}

  2. Click the project you want this to control. (If there is only one,
     click it anyway — tokens live inside a project, not above it.)

  3. In the left sidebar, click "Security", then the "API tokens" tab.

  4. Click "Generate API token".

  5. Give it a description you will recognise later, such as:  agent toolkit

  6. Choose "Read & Write".

     This is the one choice that matters and it cannot be changed afterwards.
     "Read" can list things but cannot create, resize or delete anything.

  7. Click "Generate API token".

  8. Hetzner shows the token once and never again. Click the copy icon.

STEP 2 — paste it in

  Open this file in any text editor:

     ${providerPath(SPEC.provider)}

  Find the line that starts with ${keys.token}= and paste the token
  straight after the "=", with no quotes and no spaces. Save the file.

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
    throw new Error(name ? `There is no project called "${name}".` : 'Nothing to verify yet. Run:  node scripts/setup.mjs add <a-name-for-it>');
  }
  if (!wanted.complete) {
    console.error(
      `Nothing has been pasted in for "${wanted.name}" yet.\n\n` +
      `Open this file, paste the token after ${SPEC.fields.token}_${wanted.slug}= and save it:\n` +
      `  ${providerPath(SPEC.provider)}`,
    );
    process.exit(1);
  }

  console.log(`Checking the token for "${wanted.name}"...`);
  const result = await probe(wanted.fields.token);
  if (!result.ok) {
    console.error(
      `${result.why}\n\n` +
      'The usual causes are a partial copy, a stray space, or the token having been\n' +
      'deleted in the console. Create a fresh one and paste it again:\n' +
      `  node scripts/setup.mjs add ${wanted.name} --force`,
    );
    process.exit(1);
  }

  const writable = await probeWritable(wanted.fields.token);
  recordState(SPEC.provider, { verified_at: new Date().toISOString() });

  console.log(`
Done. The project "${wanted.name}" is connected.

  servers:  ${result.servers}
  access:   ${writable ? 'Read & Write — it can create, change and delete' : 'READ ONLY — it can list things but cannot change anything'}
${writable ? '' : `
  A read-only token cannot be upgraded. If you meant it to make changes, create a
  new one with "Read & Write" and run:  node scripts/setup.mjs add ${wanted.name} --force
`}
Hetzner does not tell us which project a token belongs to, so "${wanted.name}" is the
only label there is. It is printed on everything that changes something.

Try:  node scripts/hz.mjs servers
`);
}

// --- default / removal ---------------------------------------------------------

function use(name) {
  if (!name) {
    const targets = listTargets(SPEC).filter((t) => t.complete);
    throw new Error(`usage: use <name>\nConfigured: ${targets.map((t) => t.name).join(', ') || '(none)'}`);
  }
  const target = setDefault(SPEC, name);
  console.log(`"${target.name}" is now the default project for every command.`);
  console.log('Point a single command somewhere else with  --project <name>.');
}

function rename(from, to) {
  if (!from || !to) throw new Error('usage: rename <current-name> <new-name>');
  const target = renameTarget(SPEC, from, to);
  console.log(`"${from}" is now called "${target.name}".`);
}

function forget(name, { yes }) {
  if (!name) throw new Error('usage: forget <name> --yes');
  const target = listTargets(SPEC).find((t) => t.slug === slug(name));
  if (!target) throw new Error(`There is no project called "${name}".`);

  if (!yes) {
    console.log(`This removes the saved token for "${target.name}" from this machine.`);
    console.log('The token still exists at Hetzner — delete it there too if it is finished with:');
    console.log(`  ${CONSOLE} → the project → Security → API tokens`);
    console.log(`\nTo go ahead:  node scripts/setup.mjs forget ${target.name} --yes`);
    process.exitCode = 1;
    return;
  }
  forgetTarget(SPEC, name);
  console.log(`Removed "${target.name}" from this machine. Delete it at Hetzner as well if it is no longer needed.`);
}

// --- command line ---------------------------------------------------------------

const [command = 'status', ...rest] = process.argv.slice(2);
const positional = rest.filter((a) => !a.startsWith('--'));
const options = { force: rest.includes('--force'), yes: rest.includes('--yes') };

try {
  if (command === 'status' || command === 'list') await status();
  else if (command === 'import') await importExisting(options);
  else if (command === 'add') add(positional[0], options);
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
