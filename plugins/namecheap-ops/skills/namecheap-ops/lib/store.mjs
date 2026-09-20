#!/usr/bin/env node
// store.mjs — the shared credential store for toolkit skills.
//
// Works on macOS, Linux and Windows. Node standard library only, so a skill
// directory copied anywhere keeps working with no install step.
//
// The one rule this file exists to enforce: a secret value is never printed.
// There is deliberately no `get` on the command line. Provider scripts import
// `readSecrets()` and use the value in-process; humans and agents only ever see
// whether a value is set, never what it is.

import { existsSync, mkdirSync, readFileSync, writeFileSync, chmodSync, renameSync, statSync } from 'node:fs';
import { homedir, platform } from 'node:os';
import { join, dirname } from 'node:path';
import { pathToFileURL } from 'node:url';

const IS_WINDOWS = platform() === 'win32';

// --- locations ---------------------------------------------------------------

/**
 * Root of the store. `AGENT_TOOLKIT_HOME` wins, so an org can relocate it.
 *
 * The default carries the publisher prefix on purpose. "agent-toolkit" is a
 * generic phrase that more than one project could reasonably claim, and two
 * tools fighting over one directory would be a nasty failure to debug. Same
 * reasoning as scoped package names and reverse-DNS bundle ids: uniqueness
 * comes from the publisher.
 */
export function storeRoot() {
  const override = process.env.AGENT_TOOLKIT_HOME;
  if (override && override.trim()) return resolveHome(override.trim());
  return join(homedir(), '.itqan-agent-toolkit');
}

/** Expand a leading `~` the way a shell would; Windows users type `~` too. */
function resolveHome(p) {
  if (p === '~') return homedir();
  if (p.startsWith('~/') || p.startsWith('~\\')) return join(homedir(), p.slice(2));
  return p;
}

export const credentialsDir = () => join(storeRoot(), 'credentials');
export const statePath = () => join(storeRoot(), 'state', 'setup.json');
export const providerPath = (provider) => join(credentialsDir(), `${assertProvider(provider)}.env`);

function assertProvider(provider) {
  if (!/^[a-z0-9][a-z0-9-]*$/.test(provider || '')) {
    throw new Error(`invalid provider name '${provider}' — use lowercase letters, digits and hyphens`);
  }
  return provider;
}

// --- permissions -------------------------------------------------------------
// chmod is a no-op on Windows. Rather than pretend otherwise, tighten where we
// can and report honestly where we cannot, so the user can decide.

function harden(path, mode) {
  if (IS_WINDOWS) return { hardened: false, reason: 'Windows: file permissions not enforced by chmod' };
  try {
    chmodSync(path, mode);
    return { hardened: true };
  } catch (err) {
    return { hardened: false, reason: err.message };
  }
}

export function permissionWarnings() {
  const warnings = [];
  if (IS_WINDOWS) {
    warnings.push(
      `Windows does not honour Unix file permissions. ${credentialsDir()} is readable by ` +
      `any process running as you. Keep the machine's disk encryption on, and do not sync this folder to cloud storage.`,
    );
    return warnings;
  }
  for (const [path, want] of [[credentialsDir(), 0o700], [storeRoot(), 0o700]]) {
    if (!existsSync(path)) continue;
    const mode = statSync(path).mode & 0o777;
    if (mode & 0o077) warnings.push(`${path} is mode ${mode.toString(8)}, expected ${want.toString(8)} — others can read it`);
  }
  return warnings;
}

// --- env files ---------------------------------------------------------------
// Parsed, never sourced. `source file.env` is shell-only and would execute
// whatever the file contains; this reads it as data on every platform.

export function parseEnv(text) {
  const out = {};
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const eq = line.indexOf('=');
    if (eq < 1) continue;
    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    out[key] = value;
  }
  return out;
}

/** Read a provider's secrets. Import this; never expose it through the CLI. */
export function readSecrets(provider) {
  const path = providerPath(provider);
  if (!existsSync(path)) return {};
  return parseEnv(readFileSync(path, 'utf8'));
}

/** True when the key holds a non-placeholder value. */
export function hasSecret(provider, key) {
  const value = readSecrets(provider)[key];
  return Boolean(value && !/^(<|paste|your[-_])/i.test(value));
}

function ensureDir(path, mode) {
  if (!existsSync(path)) mkdirSync(path, { recursive: true });
  // Harden the root too. `recursive: true` creates parents with the default
  // umask, which on most systems leaves the root world-readable.
  harden(storeRoot(), 0o700);
  harden(path, mode);
}

/** Write keys into a provider file, preserving comments and unrelated keys. */
export function writeSecrets(provider, updates) {
  const path = providerPath(provider);
  ensureDir(dirname(path), 0o700);

  const existing = existsSync(path) ? readFileSync(path, 'utf8') : '';
  const lines = existing ? existing.split(/\r?\n/) : [];
  const pending = new Map(Object.entries(updates));

  const merged = lines.map((line) => {
    const match = /^([A-Za-z_][A-Za-z0-9_]*)=/.exec(line.trim());
    if (!match || !pending.has(match[1])) return line;
    const key = match[1];
    const value = pending.get(key);
    pending.delete(key);
    return `${key}=${value}`;
  });
  for (const [key, value] of pending) merged.push(`${key}=${value}`);

  // Write to a sibling temp file, then rename, so an interrupted write cannot
  // leave a half-written credential behind.
  const tmp = `${path}.tmp`;
  writeFileSync(tmp, `${merged.join('\n').replace(/\n+$/, '')}\n`, 'utf8');
  harden(tmp, 0o600);
  renameSync(tmp, path);
  harden(path, 0o600);
  return path;
}

/**
 * Create the file a human is about to edit: every key present, commented, with
 * a placeholder. The user opens this in their editor and pastes one value.
 */
export function scaffold(provider, vars, header = '') {
  const path = providerPath(provider);
  ensureDir(dirname(path), 0o700);
  if (existsSync(path)) return { path, created: false };

  const body = [
    `# ${provider} credentials`,
    '#',
    ...(header ? [...header.split('\n').map((l) => `# ${l}`), '#'] : []),
    '# Paste the value after the "=" with no quotes and no spaces, then save.',
    '# Anything after a "#" is a note and is ignored.',
    '',
    ...vars.flatMap(({ name, note }) => [...(note ? [`# ${note}`] : []), `${name}=`, '']),
  ].join('\n');

  writeFileSync(path, body, 'utf8');
  harden(path, 0o600);
  return { path, created: true };
}

// --- state -------------------------------------------------------------------
// Non-secret bookkeeping: what is configured, when it was last verified, and
// the token's id so it can be revoked later. Never the value.

export function readState() {
  const path = statePath();
  if (!existsSync(path)) return { providers: {} };
  try {
    return JSON.parse(readFileSync(path, 'utf8'));
  } catch {
    return { providers: {} };
  }
}

export function recordState(provider, patch) {
  const path = statePath();
  ensureDir(dirname(path), 0o700);
  const state = readState();
  state.providers ??= {};
  state.providers[provider] = { ...(state.providers[provider] || {}), ...patch };
  writeFileSync(path, `${JSON.stringify(state, null, 2)}\n`, 'utf8');
  harden(path, 0o600);
  return path;
}

// --- command line ------------------------------------------------------------

const COMMANDS = {
  path() {
    console.log(storeRoot());
  },

  status() {
    const root = storeRoot();
    console.log(`store: ${root}`);
    console.log(process.env.AGENT_TOOLKIT_HOME ? '  (location set by AGENT_TOOLKIT_HOME)' : '  (default location)');
    const state = readState();
    const names = Object.keys(state.providers || {});
    if (!names.length) {
      console.log('\nno providers set up yet');
    } else {
      console.log('');
      for (const name of names) {
        const info = state.providers[name];
        const ok = existsSync(providerPath(name));
        console.log(`  ${name.padEnd(14)} ${ok ? 'configured' : 'MISSING FILE'}   last verified: ${info.verified_at || 'never'}`);
      }
    }
    const warnings = permissionWarnings();
    if (warnings.length) {
      console.log('');
      for (const w of warnings) console.log(`  ! ${w}`);
    }
  },

  // Reports whether a key is set. Prints the length so a user who mis-pasted can
  // tell, without revealing the value itself.
  has([provider, key]) {
    if (!provider || !key) throw new Error('usage: has <provider> <KEY>');
    const secrets = readSecrets(provider);
    const value = secrets[key];
    if (!existsSync(providerPath(provider))) {
      console.log(`${key}: not set up yet — no ${provider} file exists`);
      process.exitCode = 1;
      return;
    }
    if (!value) {
      console.log(`${key}: empty — the file is ready but nothing has been pasted in yet`);
      console.log(`  open: ${providerPath(provider)}`);
      process.exitCode = 1;
      return;
    }
    if (/^(<|paste|your[-_])/i.test(value)) {
      console.log(`${key}: still shows the example text, not a real value`);
      console.log(`  open: ${providerPath(provider)}`);
      process.exitCode = 1;
      return;
    }
    console.log(`${key}: set (${value.length} characters)`);
  },

  scaffold([provider, ...rest]) {
    if (!provider) throw new Error('usage: scaffold <provider> --var NAME[:note] [--var ...]');
    const vars = [];
    for (let i = 0; i < rest.length; i += 1) {
      if (rest[i] !== '--var') continue;
      const [name, ...noteParts] = String(rest[i + 1] || '').split(':');
      if (name) vars.push({ name, note: noteParts.join(':').trim() });
    }
    if (!vars.length) throw new Error('at least one --var NAME is required');
    const { path, created } = scaffold(provider, vars);
    console.log(created ? `created ${path}` : `already exists: ${path}`);
    console.log('\nOpen that file, paste the value after the "=", and save it.');
  },

  // Accepts a value on stdin so a minted secret never appears in a command line,
  // a process list, or shell history.
  async 'set-stdin'([provider, key]) {
    if (!provider || !key) throw new Error('usage: set-stdin <provider> <KEY>   (value on stdin)');
    const chunks = [];
    for await (const chunk of process.stdin) chunks.push(chunk);
    const value = Buffer.concat(chunks).toString('utf8').trim();
    if (!value) throw new Error('nothing on stdin');
    const path = writeSecrets(provider, { [key]: value });
    console.log(`${key} written to ${path} (${value.length} characters)`);
  },

  record([provider, json]) {
    if (!provider || !json) throw new Error('usage: record <provider> <json>');
    console.log(`recorded in ${recordState(provider, JSON.parse(json))}`);
  },
};

// pathToFileURL, not string concatenation — a Windows path like C:\... is not a
// valid URL and would silently never match.
const isMain = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
if (isMain) {
  const [command, ...args] = process.argv.slice(2);
  const handler = COMMANDS[command];
  if (!handler) {
    console.error(`usage: store.mjs <${Object.keys(COMMANDS).join('|')}> [args]`);
    process.exit(2);
  }
  try {
    await handler(args);
  } catch (err) {
    console.error(`error: ${err.message}`);
    process.exit(1);
  }
}
