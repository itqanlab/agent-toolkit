#!/usr/bin/env node
// setup.mjs — connect one or more Namecheap accounts.
//
// Namecheap does not issue tokens. What it issues is a username, an API key, and
// a list of addresses allowed to use them, edited by hand in the dashboard. So
// setup has a job the other providers' setups do not: not just "is the key
// right" but "will Namecheap accept requests from where this machine sits", and
// if not, what to do about it.
//
//   status  — what is connected, and whether Namecheap accepts it from here
//   import  — adopt credentials this machine already has
//   add     — connect an account by hand
//   verify  — check what was pasted and remember that it works
//   relay   — send this account's requests through an SSH host
//   use     — choose the default account
//   forget  — remove one from this machine

import { providerPath, recordState, permissionWarnings } from '../lib/store.mjs';
import { listTargets, scaffoldTarget, setDefault, forgetTarget, renameTarget, slug, defaultTargetName } from '../lib/targets.mjs';
import { findExisting, findInEnvFile, findSshServers } from '../lib/adopt.mjs';
import { probe, publicIp } from '../lib/transport.mjs';
import { SPEC } from './nc.mjs';

const API_PAGE = 'https://ap.www.namecheap.com/settings/tools/apiaccess/';

// The names other tools use for the same values, most common first. `ip` is the
// address the old setup was whitelisted for; it is not a credential, but it is
// the clue that says whether a relay is needed.
const ALIASES = {
  user: ['NAMECHEAP_API_USER', 'NAMECHEAP_USERNAME', 'NAMECHEAP_USER'],
  key: ['NAMECHEAP_API_KEY', 'NAMECHEAP_KEY'],
  ip: ['NAMECHEAP_CLIENT_IP', 'NAMECHEAP_IP'],
};
const REQUIRED = ['user', 'key'];

const asAccount = (name, t) => ({ name, user: t.user, key: t.key, relay: t.relay || '' });
const quoted = (p) => (/\s/.test(p) ? `"${p}"` : p);

const [command = 'status', ...rest] = process.argv.slice(2);
const opt = (name) => { const at = rest.indexOf(`--${name}`); return at === -1 ? '' : rest[at + 1] || ''; };
const positional = rest.filter((a, i) => !a.startsWith('--') && !['relay', 'file', 'name'].some((f) => rest[i - 1] === `--${f}`));
const options = { force: rest.includes('--force'), yes: rest.includes('--yes'), noRelay: rest.includes('--no-relay') };

// --- status ------------------------------------------------------------------

async function status() {
  const targets = listTargets(SPEC);
  if (!targets.length) {
    console.log('No Namecheap account is connected yet.\n');
    const existing = findExisting(ALIASES, { required: REQUIRED });
    if (existing.length) {
      console.log(`This machine already has ${existing.length} Namecheap credential(s) configured elsewhere:`);
      for (const e of existing) console.log(`  ${e.source}`);
      console.log('\nAdopt them — nothing new to create:\n  node scripts/setup.mjs import');
    } else {
      console.log('Connect one:\n  node scripts/setup.mjs add <a-name-for-it>');
      console.log('\nIf the keys already sit in a .env file for some script, adopt them from there:');
      console.log('  node scripts/setup.mjs import --file <path-to-that-file>');
    }
    process.exitCode = 1;
    return;
  }

  const fallback = defaultTargetName(SPEC);
  console.log(`${targets.length} Namecheap account(s) on this machine\n`);
  for (const target of targets) {
    const mark = slug(fallback || '') === target.slug ? '*' : ' ';
    if (!target.complete) {
      console.log(`${mark} ${target.name.padEnd(20)} waiting for the username and key to be pasted in`);
      continue;
    }
    const result = await probe(asAccount(target.name, target.fields));
    const via = target.fields.relay ? `via relay${result.ip ? ` (${result.ip})` : ''}` : `direct${result.ip ? ` (${result.ip})` : ''}`;
    console.log(`${mark} ${target.name.padEnd(20)} ${result.ok ? `works — ${via}, balance ${result.balance}` : `NOT WORKING — ${result.why.split('\n')[0]}`}`);
  }
  console.log('\n* is the default. Any command can be pointed elsewhere with --account <name>.');
  for (const warning of permissionWarnings()) console.log(`\n! ${warning}`);
}

// --- import ------------------------------------------------------------------

async function importExisting() {
  const file = opt('file');
  let existing;
  try {
    existing = file ? findInEnvFile(file, ALIASES, { required: REQUIRED }) : findExisting(ALIASES, { required: REQUIRED });
  } catch (err) {
    console.error(err.message);
    process.exit(1);
  }
  if (!existing.length) {
    console.log(file
      ? `${file} does not hold a Namecheap username and key (looked for ${ALIASES.user.join(', ')} and ${ALIASES.key.join(', ')}).`
      : 'No Namecheap credentials found in the tool configurations on this machine.');
    console.log('\nConnect one by hand instead:\n  node scripts/setup.mjs add <a-name-for-it>');
    if (!file) console.log('Or, if they are in a .env file:  node scripts/setup.mjs import --file <path>');
    process.exitCode = 1;
    return;
  }

  const mine = await publicIp('').catch(() => '');
  const known = listTargets(SPEC);
  const plan = existing.map((entry) => {
    const already = known.find((t) => t.fields.key && t.fields.key === entry.values.key);
    const name = already ? already.name : (opt('name') || entry.suggestedName);

    // The old setup was whitelisted for some address. If that is not where this
    // machine sits, the credentials are useless from here without a relay — so
    // look for a server the agent can already reach at that address.
    let relay = opt('relay');
    let relayNote = relay ? 'given on the command line' : '';
    const wanted = entry.values.ip;
    if (!relay && !options.noRelay && wanted && wanted !== mine) {
      const ssh = findSshServers(wanted)[0];
      if (ssh) {
        relay = `${ssh.keyPath ? `-i ${quoted(ssh.keyPath)} ` : ''}${ssh.user}@${ssh.host}`;
        relayNote = `found an ssh entry for ${wanted} in ${ssh.source}`;
      }
    }
    return { ...entry, name, already: Boolean(already), relay, relayNote, wanted, mine };
  });

  console.log(`Found ${plan.length} Namecheap credential(s) already configured:\n`);
  for (const p of plan) {
    console.log(`  ${p.source}`);
    console.log(`      would be called "${p.name}"${p.already ? '   (already connected — will be left alone)' : ''}`);
    if (p.wanted) console.log(`      it was set up for the address ${p.wanted}; this machine is ${p.mine || 'unknown'}`);
    if (p.relay) console.log(`      relay: ${p.relay}   (${p.relayNote})`);
    else if (p.wanted && p.wanted !== p.mine) {
      console.log('      no relay found — from here Namecheap will refuse it unless this machine\'s address is also whitelisted.');
      console.log('      to route through a server that has that address:  --relay "-i <key> <user>@<host>"');
    }
  }

  if (!options.yes) {
    console.log('\nNothing has been changed. To adopt them:\n  node scripts/setup.mjs import' + (file ? ` --file ${file}` : '') + (opt('name') ? ` --name ${opt('name')}` : '') + (opt('relay') ? ` --relay ${quoted(opt('relay'))}` : '') + ' --yes');
    console.log('\nThe values are copied into this toolkit\'s own credential file. The originals stay');
    console.log('where they are and keep working.');
    return;
  }

  let added = 0;
  for (const p of plan) {
    if (p.already) continue;
    const result = await probe({ name: p.name, user: p.values.user, key: p.values.key, relay: p.relay });
    // A wrong key is worth refusing. A refused address is not: the key is fine
    // and the fix is on the dashboard, so keep it and say what is left to do.
    if (!result.ok && result.code === '1011102') {
      console.log(`\n"${p.name}" was skipped — ${result.why.split('\n')[0]}`);
      continue;
    }
    scaffoldTarget(SPEC, p.name, { user: p.values.user, key: p.values.key, relay: p.relay });
    recordState(SPEC.provider, { verified_at: result.ok ? new Date().toISOString() : undefined });
    console.log(result.ok
      ? `\nconnected "${p.name}" — balance ${result.balance}, requests come from ${result.ip}${p.relay ? ' (relay)' : ''}`
      : `\nsaved "${p.name}", but it does not work yet:\n${result.why}`);
    added += 1;
  }
  console.log(added ? `\n${added} account(s) added. See them with:  node scripts/setup.mjs status` : '\nNothing new to add.');
}

// --- add / verify -------------------------------------------------------------

async function add(name) {
  if (!name) throw new Error('usage: add <a-name-for-it> [--relay "<ssh options>"]   e.g. add mycompany');

  const existing = listTargets(SPEC).find((t) => t.slug === slug(name));
  if (existing?.complete && !options.force) {
    console.log(`"${existing.name}" is already connected. Nothing to do.`);
    console.log('To replace its key, run this again with --force.');
    return;
  }

  const relay = opt('relay');
  const { keys } = scaffoldTarget(SPEC, name, options.force ? { user: '', key: '', ...(relay ? { relay } : {}) } : (relay ? { relay } : {}));
  const ip = await publicIp(relay).catch(() => '');

  console.log(`
Connecting a Namecheap account called "${name}". This takes about five minutes,
most of it on Namecheap's side.

Namecheap does not have tokens. It has an API key, and a list of addresses that
are allowed to use it. Both are set on one page.

STEP 1 — switch API access on

  1. Open this page and sign in:

       ${API_PAGE}

     If that address does not open, go to Profile → Tools → "Namecheap API
     Access" from the dashboard instead. (I could not open Namecheap's own help
     pages to confirm the menu names, so they may differ slightly.)

  2. Turn it on. Namecheap may say the account does not qualify yet. Its
     published rule is roughly: a balance, or enough spend, or enough domains.
     That is Namecheap's decision and cannot be worked around from here.

  3. Copy the API key it shows. Your username is the one you sign in with.

STEP 2 — allow the address requests will come from

  On the same page, under "Whitelisted IPs", add:

       ${ip || '(could not be worked out — run this again once the internet is reachable)'}
${relay
    ? `\n  That is the address of the relay (${relay}), so it never changes.`
    : `
  That is this machine's public address. If you are on home or mobile internet
  it will change, and every change means editing this list again. If you have a
  server with a fixed address, send requests through it instead:
       node scripts/setup.mjs relay ${name} "<user>@<server address>"`}

STEP 3 — paste them in

  Open this file in any text editor:

     ${providerPath(SPEC.provider)}

  Fill in these two lines, straight after the "=", with no quotes and no spaces:

     ${keys.user}=   your Namecheap username
     ${keys.key}=    the API key

  Save the file. Do not paste the key into the chat.

STEP 4 — tell me you are done

     node scripts/setup.mjs verify ${name}
`);
}

async function verify(name) {
  const targets = listTargets(SPEC);
  const wanted = name
    ? targets.find((t) => t.slug === slug(name))
    : targets.filter((t) => t.complete).pop() || targets[targets.length - 1];

  if (!wanted) {
    throw new Error(name ? `There is no account called "${name}".` : 'Nothing to verify yet. Run:  node scripts/setup.mjs add <a-name-for-it>');
  }
  if (!wanted.complete) {
    console.error(
      `Nothing has been pasted in for "${wanted.name}" yet.\n\n` +
      `Open this file and fill in ${SPEC.fields.user}_${wanted.slug} and ${SPEC.fields.key}_${wanted.slug}:\n` +
      `  ${providerPath(SPEC.provider)}`,
    );
    process.exit(1);
  }

  console.log(`Checking "${wanted.name}" with Namecheap...`);
  const result = await probe(asAccount(wanted.name, wanted.fields));
  if (!result.ok) {
    console.error(`\n${result.why}`);
    process.exit(1);
  }
  recordState(SPEC.provider, { verified_at: new Date().toISOString() });

  console.log(`
Done. The account "${wanted.name}" is connected.

  balance:   ${result.balance}
  requests:  ${wanted.fields.relay ? `through the relay, as ${result.ip}` : `directly from this machine, as ${result.ip}`}

Namecheap does not say which account a key belongs to, so "${wanted.name}" is the
only label there is. It is printed on everything that changes something.

Try:  node scripts/nc.mjs domains
`);
}

// --- relay / default / removal -------------------------------------------------

async function relay(name, value) {
  if (!name || !value) throw new Error('usage: relay <name> "<ssh options and user@host>"   or   relay <name> none');
  const target = listTargets(SPEC).find((t) => t.slug === slug(name));
  if (!target) throw new Error(`There is no account called "${name}".`);
  const setting = value === 'none' ? '' : value;
  scaffoldTarget(SPEC, target.name, { relay: setting });
  if (!setting) return console.log(`"${target.name}" now sends requests directly from this machine.`);

  const ip = await publicIp(setting);
  console.log(`"${target.name}" now sends requests through ${setting}.`);
  console.log(`Namecheap will see the address ${ip}. It must be on the whitelist:`);
  console.log(`  ${API_PAGE}  →  Whitelisted IPs`);
  console.log(`\nThen check it:  node scripts/setup.mjs verify ${target.name}`);
}

function use(name) {
  if (!name) {
    const targets = listTargets(SPEC).filter((t) => t.complete);
    throw new Error(`usage: use <name>\nConfigured: ${targets.map((t) => t.name).join(', ') || '(none)'}`);
  }
  const target = setDefault(SPEC, name);
  console.log(`"${target.name}" is now the default account for every command.`);
  console.log('Point a single command somewhere else with  --account <name>.');
}

function rename(from, to) {
  if (!from || !to) throw new Error('usage: rename <current-name> <new-name>');
  const target = renameTarget(SPEC, from, to);
  console.log(`"${from}" is now called "${target.name}".`);
}

function forget(name) {
  if (!name) throw new Error('usage: forget <name> --yes');
  const target = listTargets(SPEC).find((t) => t.slug === slug(name));
  if (!target) throw new Error(`There is no account called "${name}".`);

  if (!options.yes) {
    console.log(`This removes the saved username and key for "${target.name}" from this machine.`);
    console.log('The key still works at Namecheap. To end that, switch API access off or regenerate the key:');
    console.log(`  ${API_PAGE}`);
    console.log(`\nTo go ahead:  node scripts/setup.mjs forget ${target.name} --yes`);
    process.exitCode = 1;
    return;
  }
  forgetTarget(SPEC, name);
  console.log(`Removed "${target.name}" from this machine. Regenerate or disable the key at Namecheap if it is finished with.`);
}

// --- command line ---------------------------------------------------------------

try {
  if (command === 'status' || command === 'list') await status();
  else if (command === 'import') await importExisting();
  else if (command === 'add') await add(positional[0]);
  else if (command === 'verify' || command === 'finish') await verify(positional[0]);
  else if (command === 'relay') await relay(positional[0], positional[1]);
  else if (command === 'use') use(positional[0]);
  else if (command === 'rename') rename(positional[0], positional[1]);
  else if (command === 'forget' || command === 'remove') forget(positional[0]);
  else {
    console.error('usage: setup.mjs <status|import|add|verify|relay|use|rename|forget> [name] [--file <path>] [--relay "<ssh>"] [--force] [--yes]');
    process.exit(2);
  }
} catch (err) {
  console.error(`error: ${err.message}`);
  process.exit(1);
}
