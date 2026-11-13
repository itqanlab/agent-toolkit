#!/usr/bin/env node
// setup.mjs: set up and check the Zernio workspace keys that zernio-hub.mjs reads.
//
//   node scripts/setup.mjs path               print the keys file path (creates it, mode 600)
//   node scripts/setup.mjs add <name>         add an empty ZERNIO_KEY_<NAME>= line to fill in
//   node scripts/setup.mjs status             each workspace: key set or not, and its accounts
//   node scripts/setup.mjs status --json      the same, as JSON
//
// <name> is any short name: a letter (a, b, c) or a word (brand, client_2). The keys live in
// the toolkit credential store (lib/store.mjs), the same store every toolkit skill uses.
//
// No command prints a key. `status` reports the length of a key, which is enough to spot a
// bad paste, and asks Zernio which accounts that key can see.
import { recordState, scaffold, writeSecrets } from '../lib/store.mjs';
import { PROVIDER, allWorkspaces, keyName, keysFile, validName } from '../lib/workspaces.mjs';

const API = 'https://api.zernio.com/v1';
const HEADER = [
  'One line per Zernio workspace: ZERNIO_KEY_<NAME>=<api key>.',
  'NAME is letters, digits and underscores, for example ZERNIO_KEY_A or ZERNIO_KEY_BRAND.',
  'Make the key in that workspace\'s Zernio settings. Restart the agent after a change.',
].join('\n');

const ensureFile = () => scaffold(PROVIDER, [], HEADER).path;

async function accounts(key) {
  let res;
  try {
    res = await fetch(`${API}/accounts`, { headers: { Authorization: `Bearer ${key}` } });
  } catch (e) {
    return { error: `could not reach Zernio (${e.cause?.code || e.message}). Check the internet connection.` };
  }
  if (res.status === 401 || res.status === 403) return { error: 'Zernio refused this key. Make a new one in that workspace and paste it again.' };
  if (!res.ok) return { error: `Zernio answered HTTP ${res.status}` };
  const body = await res.json();
  return {
    accounts: (body.accounts || []).map((a) => ({
      platform: a.platform,
      username: a.username,
      id: a._id,
      active: a.isActive !== false,
    })),
  };
}

async function status(json) {
  const all = allWorkspaces();
  const rows = [];
  for (const ws of Object.keys(all).sort()) {
    const row = { workspace: ws, keyLength: all[ws].length };
    if (!all[ws]) row.error = 'the line is there but the key is empty. Paste the key after the = sign.';
    else Object.assign(row, await accounts(all[ws]));
    rows.push(row);
  }
  const ready = rows.filter((r) => !r.error).map((r) => r.workspace);
  if (ready.length) recordState(PROVIDER, { workspaces: ready, verifiedAt: new Date().toISOString() });

  if (json) {
    console.log(JSON.stringify({ file: keysFile(), workspaces: rows }, null, 2));
  } else {
    console.log(`keys file: ${keysFile()}`);
    if (!rows.length) console.log('no workspaces yet. Run: node scripts/setup.mjs add <name>');
    for (const r of rows) {
      if (r.error) {
        console.log(`\n${r.workspace}: NOT READY (key length ${r.keyLength}). ${r.error}`);
        continue;
      }
      console.log(`\n${r.workspace}: ok, ${r.accounts.length} connected account(s)`);
      for (const a of r.accounts) console.log(`  ${a.platform.padEnd(10)} ${a.username}  ${a.id}${a.active ? '' : '  (inactive)'}`);
    }
  }
  if (!rows.length || rows.some((r) => r.error)) process.exitCode = 1;
}

function add(name) {
  if (!name || !validName(name)) {
    console.error('give a short name of letters, digits or underscores, for example: node scripts/setup.mjs add a');
    process.exit(2);
  }
  const ws = name.toLowerCase();
  ensureFile();
  if (ws in allWorkspaces()) {
    console.log(`${keyName(ws)} is already in ${keysFile()}`);
    return;
  }
  writeSecrets(PROVIDER, { [keyName(ws)]: '' });
  console.log(`added an empty ${keyName(ws)}= line to ${keysFile()}`);
  console.log('open that file and paste the key right after the = sign, then run: node scripts/setup.mjs status');
}

const [cmd, arg] = process.argv.slice(2);
if (cmd === 'path') console.log(ensureFile());
else if (cmd === 'add') add(arg);
else if (cmd === 'status') await status(process.argv.includes('--json'));
else {
  console.error('usage: node scripts/setup.mjs path | add <name> | status [--json]');
  process.exit(2);
}
