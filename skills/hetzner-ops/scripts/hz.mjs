#!/usr/bin/env node
// hz.mjs — thin Hetzner Cloud API client plus the everyday commands.
//
// The token is read from the shared credential store and used in-process. It is
// never printed, never passed on a command line, and never written to a log.
//
// Two things shape everything here and are worth reading before changing it:
//
//   1. A Hetzner token belongs to ONE project and will not tell you which. There
//      is no "whoami". So the local target name is the only label a user has,
//      and it is printed on every command that changes something.
//   2. Most changes are asynchronous. Creating, resizing, attaching and even
//      rebooting return an "action" that is still running. Reporting the action
//      id back to someone who asked for a server is useless, so anything that
//      starts one waits for it to finish and reports the outcome instead.

import { readSecrets } from '../lib/store.mjs';
import { resolveTarget, takeTargetFlag } from '../lib/targets.mjs';

const API = 'https://api.hetzner.cloud/v1';
const USER_AGENT = 'itqan-agent-toolkit/1.0 (+https://github.com/itqanlab/agent-toolkit)';

export const SPEC = {
  provider: 'hetzner',
  label: 'Hetzner project',
  prefix: 'HETZNER',
  flag: 'project',
  fields: { token: 'HETZNER_TOKEN' },
};

export class HetznerError extends Error {
  constructor(message, { status, code } = {}) {
    super(message);
    this.name = 'HetznerError';
    this.status = status;
    this.code = code;
  }
}

// The project a command is acting on. Set once at startup so every call — and
// every message printed — refers to the same place.
let current = null;

export function useProject(name) {
  current = resolveTarget(SPEC, name);
  return current;
}

export function project() {
  if (!current) current = resolveTarget(SPEC, '');
  return current;
}

function token() {
  const value = project().fields.token;
  if (!value) {
    throw new HetznerError('No Hetzner token saved. Run:  node scripts/setup.mjs add <a-name-for-it>');
  }
  return value;
}

/** One call against the Hetzner Cloud API. Returns the parsed body. */
export async function request(path, { method = 'GET', body, query } = {}) {
  const url = new URL(API + path);
  for (const [k, v] of Object.entries(query || {})) {
    if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, String(v));
  }

  const init = {
    method,
    headers: {
      Authorization: `Bearer ${token()}`,
      'User-Agent': USER_AGENT,
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  };

  let response;
  for (let attempt = 1; ; attempt += 1) {
    try {
      response = await fetch(url, init);
    } catch (err) {
      if (attempt >= 3) {
        throw new HetznerError(`Could not reach Hetzner (${err.message}). Check the internet connection and try again.`);
      }
      await new Promise((r) => setTimeout(r, attempt * 500));
      continue;
    }

    // Hetzner allows 3600 requests an hour per project and says how long to wait
    // when that runs out. Waiting is almost always what the caller wants, since
    // the alternative is failing a half-finished sequence of changes.
    if (response.status === 429 && attempt < 3) {
      const wait = Number(response.headers.get('retry-after') || 5);
      console.error(`(Hetzner is rate limiting this project — waiting ${wait}s)`);
      await new Promise((r) => setTimeout(r, Math.min(wait, 60) * 1000));
      continue;
    }
    break;
  }

  const text = await response.text();
  if (!text.trim()) {
    if (response.ok) return {};
    throw new HetznerError(`Hetzner rejected the request (HTTP ${response.status}).`, { status: response.status });
  }

  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    throw new HetznerError(`Hetzner returned a non-JSON response (HTTP ${response.status})`, { status: response.status });
  }

  if (payload.error) throw new HetznerError(explain(payload.error, response.status), { status: response.status, code: payload.error.code });
  if (!response.ok) throw new HetznerError(`Hetzner rejected the request (HTTP ${response.status}).`, { status: response.status });
  return payload;
}

/** Hetzner's error codes, rewritten for someone who has never seen them. */
function explain(error, status) {
  const { code, message, details } = error || {};
  const where = `(project "${project().name}")`;

  switch (code) {
    case 'unauthorized':
      return (
        `Hetzner did not accept the saved token for ${where}.\n` +
        'It may have been deleted in the console, or pasted incompletely. Replace it with:\n' +
        `  node scripts/setup.mjs add ${project().name} --force`
      );
    case 'forbidden':
      return (
        `That token is read-only ${where}, so it cannot make this change.\n` +
        'Hetzner sets read vs read-write when the token is created and it cannot be changed afterwards.\n' +
        `Create a new one with "Read & Write" and run:  node scripts/setup.mjs add ${project().name} --force`
      );
    case 'not_found':
      return `Hetzner has no such thing in ${where}: ${message}`;
    case 'uniqueness_error':
      return `That name is already taken in ${where}. Names must be unique per project: ${message}`;
    case 'resource_limit_exceeded':
      return (
        `This project has hit a Hetzner limit: ${message}\n` +
        'New accounts start with a low server limit that rises after the first invoice is paid.\n' +
        'Raising it is a support request in the Hetzner console.'
      );
    case 'resource_unavailable':
      return (
        `Hetzner has none of that available right now: ${message}\n` +
        'This is normally a server type sold out in one location — try another location, or another type.'
      );
    case 'invalid_input': {
      const fields = (details?.fields || []).map((f) => `  ${f.name}: ${(f.messages || []).join('; ')}`).join('\n');
      return `Hetzner rejected the details of this request:\n${fields || `  ${message}`}`;
    }
    case 'rate_limit_exceeded':
      return 'This project has used its hourly Hetzner API allowance. Wait a few minutes and try again.';
    case 'protected':
      return (
        `That is delete-protected in ${where}, so Hetzner refused: ${message}\n` +
        'Protection is turned off in the Hetzner console, or with a change_protection call.'
      );
    default:
      return `${message || 'Hetzner rejected the request'}${code ? ` (${code})` : ''}${status ? ` [HTTP ${status}]` : ''}`;
  }
}

/** Follow pagination to the end. `key` is the array's name in the response. */
export async function requestAll(path, key, options = {}) {
  const out = [];
  for (let page = 1; ; page += 1) {
    const payload = await request(path, { ...options, query: { ...options.query, page, per_page: 50 } });
    out.push(...(payload[key] || []));
    const next = payload.meta?.pagination?.next_page;
    if (!next) return out;
  }
}

/**
 * Wait for an action to finish.
 *
 * Nearly every change is asynchronous, and the id of a running action is not an
 * answer to "did it work". Poll until it resolves, then say so in words.
 */
export async function waitForAction(action, { label = action?.command, quiet = false } = {}) {
  if (!action?.id) return action;
  const started = Date.now();
  let seen = action;

  while (seen.status === 'running') {
    if (Date.now() - started > 10 * 60_000) {
      throw new HetznerError(
        `"${label}" is still running after ten minutes, which is much longer than normal.\n` +
        `Check it in the Hetzner console; the action id is ${seen.id}.`,
      );
    }
    await new Promise((r) => setTimeout(r, 2000));
    seen = (await request(`/actions/${seen.id}`)).action;
    if (!quiet && seen.progress) process.stderr.write(`\r  ${label}... ${seen.progress}%   `);
  }
  if (!quiet) process.stderr.write('\r                                   \r');

  if (seen.status === 'error') {
    throw new HetznerError(`Hetzner could not finish "${label}": ${seen.error?.message || 'no reason given'}`);
  }
  return seen;
}

// --- lookups ----------------------------------------------------------------

/** Find a server by name, or by id when given digits. Names are per project. */
export async function findServer(nameOrId) {
  if (/^\d+$/.test(String(nameOrId))) return (await request(`/servers/${nameOrId}`)).server;
  const { servers } = await request('/servers', { query: { name: nameOrId } });
  if (!servers?.length) {
    const all = await requestAll('/servers', 'servers');
    throw new HetznerError(
      `No server called "${nameOrId}" in project "${project().name}".\n` +
      `Servers here: ${all.map((s) => s.name).join(', ') || '(none)'}`,
    );
  }
  return servers[0];
}

/** Resolve a hostname to the zone that serves it, longest match wins. */
export async function findZone(hostname) {
  const zones = await requestAll('/zones', 'zones');
  const match = zones
    .filter((z) => hostname === z.name || hostname.endsWith(`.${z.name}`))
    .sort((a, b) => b.name.length - a.name.length)[0];
  if (!match) {
    throw new HetznerError(
      `No DNS zone for "${hostname}" in project "${project().name}".\n` +
      `Zones here: ${zones.map((z) => z.name).join(', ') || '(none)'}\n\n` +
      'A domain has to be added as a zone before records can be created, and its nameservers\n' +
      'have to be pointed at Hetzner at the registrar.',
    );
  }
  return match;
}

/** Hetzner stores record names relative to the zone; the apex is "@". */
export function relativeName(hostname, zoneName) {
  if (hostname === zoneName) return '@';
  return hostname.slice(0, -(zoneName.length + 1));
}

const flag = (args, name, fallback) => {
  const at = args.indexOf(`--${name}`);
  return at === -1 ? fallback : args[at + 1];
};

/**
 * Hetzner bills some accounts in euros and others in dollars, and the API says
 * which. Printing the wrong symbol next to a real price is the kind of small
 * lie that makes someone distrust everything else on the screen, so the symbol
 * is read from the account once and reused.
 */
let CURRENCY = '';
async function loadCurrency() {
  if (CURRENCY) return CURRENCY;
  const pricing = await request('/pricing').then((p) => p.pricing).catch(() => null);
  CURRENCY = ({ EUR: '\u20ac', USD: '$', GBP: '\u00a3' })[pricing?.currency] || `${pricing?.currency || ''} `;
  return CURRENCY;
}

const money = (amount) => (amount === undefined || amount === null ? '' : `${CURRENCY}${Number(amount).toFixed(2)}`);

/**
 * Where a server is. Current Hetzner responses carry `location` directly;
 * older ones nested it under `datacenter`. Both are still in the wild, and a
 * crash on a missing field would be a poor way to find that out.
 */
const locationOf = (server) => server.location || server.datacenter?.location || {};

/** The monthly price of a server, at the location it actually runs in. */
const monthly = (server) => Number(
  server.server_type?.prices?.find((p) => p.location === locationOf(server).name)?.price_monthly?.gross || 0,
);

// --- commands ---------------------------------------------------------------

const COMMANDS = {
  /** No account endpoint exists, so this proves the token works and says where. */
  async whoami() {
    const [{ servers }, pricing] = await Promise.all([
      request('/servers', { query: { per_page: 1 } }),
      request('/pricing').then((p) => p.pricing).catch(() => null),
    ]);
    const total = (await request('/servers', { query: { per_page: 1 } })).meta?.pagination?.total_entries ?? servers.length;
    console.log(`project:  ${project().name}   (the name is yours — Hetzner tokens do not carry one)`);
    console.log(`servers:  ${total}`);
    if (pricing) console.log(`currency: ${pricing.currency}, prices ${pricing.vat_rate ? `exclude ${pricing.vat_rate}% VAT` : 'as shown'}`);
  },

  async servers() {
    await loadCurrency();
    const servers = await requestAll('/servers', 'servers');
    if (!servers.length) return console.log(`no servers in project "${project().name}"`);
    console.log(`project "${project().name}" — ${servers.length} server(s)\n`);
    for (const s of servers) {
      const ip = s.public_net?.ipv4?.ip || s.private_net?.[0]?.ip || '(no public address)';
      console.log(
        `${s.name.padEnd(24)} ${s.status.padEnd(10)} ${String(ip).padEnd(16)} ` +
        `${s.server_type.name.padEnd(8)} ${String(locationOf(s).name || '').padEnd(6)} ${money(monthly(s))}/mo`,
      );
    }
  },

  async server([nameOrId]) {
    if (!nameOrId) throw new Error('usage: server <name>');
    const s = await findServer(nameOrId);
    const t = s.server_type;
    console.log(`${s.name}   ${s.status}`);
    console.log(`  address:   ${s.public_net?.ipv4?.ip || '(none)'}${s.public_net?.ipv6?.ip ? `  ${s.public_net.ipv6.ip}` : ''}`);
    console.log(`  size:      ${t.name} — ${t.cores} vCPU, ${t.memory} GB memory, ${t.disk} GB disk`);
    console.log(`  where:     ${locationOf(s).description || locationOf(s).city || '(unknown)'}`);
    console.log(`  image:     ${s.image?.description || s.image?.name || '(rebuilt or unknown)'}`);
    console.log(`  created:   ${String(s.created).slice(0, 10)}`);
    console.log(`  backups:   ${s.backup_window ? `on, taken ${s.backup_window} UTC` : 'off'}`);
    console.log(`  protected: ${s.protection?.delete ? 'yes — cannot be deleted until turned off' : 'no'}`);
    if (s.volumes?.length) console.log(`  volumes:   ${s.volumes.length} attached`);
    if (s.private_net?.length) console.log(`  networks:  ${s.private_net.map((n) => n.ip).join(', ')}`);
    console.log(`  traffic:   ${(s.outgoing_traffic / 1e12).toFixed(2)} TB out of ${(s.included_traffic / 1e12).toFixed(0)} TB included`);
  },

  /**
   * Create a server. Deliberately opinionated about SSH keys: without one,
   * Hetzner emails a root password in the clear and the box is open to password
   * login from the first second. That is the single worst default here, so it
   * takes an explicit flag, and the password is written to the credential file
   * rather than printed where it would end up in a transcript.
   */
  async create(args) {
    const [name] = args;
    const type = flag(args, 'type');
    const image = flag(args, 'image', 'ubuntu-24.04');
    const location = flag(args, 'location');
    if (!name || !type || !location) {
      throw new Error(
        'usage: create <name> --type cx22 --location hel1 [--image ubuntu-24.04] [--ssh-key <name>] [--no-ssh-key]\n' +
        '  sizes:     node scripts/hz.mjs types\n' +
        '  locations: node scripts/hz.mjs locations',
      );
    }

    const keyName = flag(args, 'ssh-key');
    const keys = await requestAll('/ssh_keys', 'ssh_keys');
    let sshKeys = [];
    if (keyName) {
      const match = keys.find((k) => k.name === keyName || String(k.id) === keyName);
      if (!match) throw new HetznerError(`No SSH key called "${keyName}" in this project. Available: ${keys.map((k) => k.name).join(', ') || '(none)'}`);
      sshKeys = [match.id];
    } else if (!args.includes('--no-ssh-key')) {
      if (!keys.length) {
        throw new HetznerError(
          'This project has no SSH key, so the only way in would be a root password sent by email.\n\n' +
          'Add your key first (one command, nothing to create by hand):\n' +
          '  node scripts/hz.mjs ssh-key-add my-laptop ~/.ssh/id_ed25519.pub\n\n' +
          'If you really want password login, pass --no-ssh-key.',
        );
      }
      sshKeys = keys.map((k) => k.id);
      console.log(`using ${keys.length === 1 ? `the SSH key "${keys[0].name}"` : `all ${keys.length} SSH keys in this project`}`);
    }

    await loadCurrency();
    console.log(`creating ${name} (${type}) in ${location}, project "${project().name}"...`);
    const payload = await request('/servers', {
      method: 'POST',
      body: {
        name,
        server_type: type,
        image,
        location,
        ssh_keys: sshKeys,
        start_after_create: true,
        public_net: { enable_ipv4: !args.includes('--no-ipv4'), enable_ipv6: true },
      },
    });

    await waitForAction(payload.action, { label: 'building the server' });
    const s = (await request(`/servers/${payload.server.id}`)).server;

    console.log(`\n${s.name} is ${s.status} at ${s.public_net?.ipv4?.ip || s.public_net?.ipv6?.ip}`);

    if (payload.root_password) {
      const { writeSecrets, providerPath } = await import('../lib/store.mjs');
      writeSecrets(SPEC.provider, { [`HETZNER_ROOT_PASSWORD_${name.toUpperCase().replace(/[^A-Z0-9]+/g, '_')}`]: payload.root_password });
      console.log(
        '\nIt was created without an SSH key, so Hetzner set a root password.\n' +
        `It has been written to  ${providerPath(SPEC.provider)}  rather than shown here.\n` +
        'Log in, add an SSH key, and turn off password login as the first thing you do.',
      );
    } else {
      console.log(`\nlog in with:  ssh root@${s.public_net?.ipv4?.ip}`);
    }
    console.log(`it costs ${money(s.server_type.prices?.find((p) => p.location === location)?.price_monthly?.gross)} a month while it exists, whether it is running or not`);
  },

  async 'power-on'([name]) {
    const s = await findServer(name);
    await waitForAction((await request(`/servers/${s.id}/actions/poweron`, { method: 'POST' })).action, { label: 'starting' });
    console.log(`${s.name} is starting up (project "${project().name}")`);
  },

  /** ACPI shutdown: the polite one. The OS closes its files. */
  async shutdown([name]) {
    const s = await findServer(name);
    await waitForAction((await request(`/servers/${s.id}/actions/shutdown`, { method: 'POST' })).action, { label: 'shutting down' });
    console.log(`${s.name} was asked to shut down (project "${project().name}")`);
    console.log('If it ignores the request, "power-off" cuts the power — see the note there.');
  },

  /**
   * Pulling the plug. Kept separate from shutdown on purpose: this is the one
   * that loses unwritten data, and calling it "off" without saying so would be
   * a trap for exactly the person this skill is written for.
   */
  async 'power-off'(args) {
    const s = await findServer(args[0]);
    if (!args.includes('--yes')) {
      console.log(`${s.name} is ${s.status}.`);
      console.log('\nThis cuts the power instantly, like pulling the cable. Anything not yet written to disk is lost.');
      console.log(`For a clean stop use:  node scripts/hz.mjs shutdown ${s.name}`);
      console.log(`To do it anyway:       node scripts/hz.mjs power-off ${s.name} --yes`);
      process.exitCode = 1;
      return;
    }
    await waitForAction((await request(`/servers/${s.id}/actions/poweroff`, { method: 'POST' })).action, { label: 'powering off' });
    console.log(`${s.name} is off (project "${project().name}"). It still costs money while it exists.`);
  },

  async reboot([name]) {
    const s = await findServer(name);
    await waitForAction((await request(`/servers/${s.id}/actions/reboot`, { method: 'POST' })).action, { label: 'rebooting' });
    console.log(`${s.name} is rebooting (project "${project().name}")`);
  },

  /**
   * Change the size. Disk growth is one-way — Hetzner cannot shrink a disk
   * afterwards, which quietly locks the server out of smaller types forever — so
   * it is opt-in rather than the default.
   */
  async resize(args) {
    const [name, type] = args;
    if (!name || !type) throw new Error('usage: resize <server> <type> [--upgrade-disk] [--yes]');
    const s = await findServer(name);
    const upgradeDisk = args.includes('--upgrade-disk');

    if (!args.includes('--yes')) {
      console.log(`${s.name} is ${s.server_type.name} (${s.server_type.cores} vCPU, ${s.server_type.memory} GB) and is ${s.status}.`);
      console.log(`\nResizing to ${type} shuts the server down first — it will be offline for a minute or two.`);
      console.log(upgradeDisk
        ? '\n--upgrade-disk grows the disk too. That cannot be undone: a server with a grown disk can never move to a smaller type again.'
        : '\nThe disk stays its current size, so the server can be moved back down later. Add --upgrade-disk to grow it (permanent).');
      console.log(`\nTo go ahead:  node scripts/hz.mjs resize ${s.name} ${type} ${upgradeDisk ? '--upgrade-disk ' : ''}--yes`);
      process.exitCode = 1;
      return;
    }

    if (s.status === 'running') {
      await waitForAction((await request(`/servers/${s.id}/actions/shutdown`, { method: 'POST' })).action, { label: 'shutting down first' });
      // Hetzner refuses the change while the machine is still winding down.
      for (let i = 0; i < 30; i += 1) {
        const now = (await request(`/servers/${s.id}`)).server;
        if (now.status === 'off') break;
        await new Promise((r) => setTimeout(r, 2000));
      }
    }
    await waitForAction((await request(`/servers/${s.id}/actions/change_type`, {
      method: 'POST', body: { server_type: type, upgrade_disk: upgradeDisk },
    })).action, { label: 'resizing' });
    await waitForAction((await request(`/servers/${s.id}/actions/poweron`, { method: 'POST' })).action, { label: 'starting again' });
    console.log(`${s.name} is now ${type} and starting up (project "${project().name}")`);
  },

  async delete(args) {
    const s = await findServer(args[0]);
    if (!args.includes('--yes')) {
      console.log(`${s.name}   ${s.status}   ${s.public_net?.ipv4?.ip || ''}   ${s.server_type.name}   created ${String(s.created).slice(0, 10)}`);
      console.log('\nDeleting destroys the server and its disk. Snapshots and volumes survive; nothing else does.');
      console.log(`Project: "${project().name}".`);
      console.log(`\nTo go ahead:  node scripts/hz.mjs delete ${s.name} --yes`);
      process.exitCode = 1;
      return;
    }
    await request(`/servers/${s.id}`, { method: 'DELETE' });
    console.log(`deleted ${s.name} from project "${project().name}"`);
  },

  async 'ssh-keys'() {
    const keys = await requestAll('/ssh_keys', 'ssh_keys');
    if (!keys.length) return console.log(`no SSH keys in project "${project().name}"`);
    for (const k of keys) console.log(`${k.name.padEnd(24)} ${k.fingerprint}`);
  },

  async 'ssh-key-add'([name, file]) {
    if (!name || !file) throw new Error('usage: ssh-key-add <name> <path-to-public-key>');
    const { readFileSync, existsSync } = await import('node:fs');
    const { homedir } = await import('node:os');
    const path = file.startsWith('~') ? file.replace(/^~/, homedir()) : file;
    if (!existsSync(path)) {
      throw new Error(
        `No file at ${path}\n` +
        'This wants the PUBLIC half of an SSH key — the file ending in .pub.\n' +
        'If there is none, create a key pair with:  ssh-keygen -t ed25519',
      );
    }
    const publicKey = readFileSync(path, 'utf8').trim();
    if (/PRIVATE KEY/.test(publicKey)) {
      throw new Error(`${path} is a PRIVATE key. Never upload that. Use the matching file ending in .pub.`);
    }
    const { ssh_key: key } = await request('/ssh_keys', { method: 'POST', body: { name, public_key: publicKey } });
    console.log(`added SSH key "${key.name}" to project "${project().name}" (${key.fingerprint})`);
  },

  async volumes() {
    const volumes = await requestAll('/volumes', 'volumes');
    if (!volumes.length) return console.log(`no volumes in project "${project().name}"`);
    for (const v of volumes) console.log(`${v.name.padEnd(24)} ${String(v.size + ' GB').padEnd(9)} ${v.server ? `attached to server ${v.server}` : 'not attached'}`);
  },

  async firewalls() {
    const firewalls = await requestAll('/firewalls', 'firewalls');
    if (!firewalls.length) return console.log(`no firewalls in project "${project().name}"`);
    for (const f of firewalls) {
      console.log(`${f.name}   applied to ${f.applied_to?.length || 0} resource(s)`);
      for (const r of f.rules || []) {
        console.log(`  ${r.direction.padEnd(4)} ${String(r.protocol).padEnd(5)} ${String(r.port || 'any').padEnd(8)} from ${(r.source_ips || r.destination_ips || []).join(', ')}`);
      }
    }
  },

  async networks() {
    const networks = await requestAll('/networks', 'networks');
    if (!networks.length) return console.log(`no private networks in project "${project().name}"`);
    for (const n of networks) console.log(`${n.name.padEnd(24)} ${n.ip_range.padEnd(18)} ${n.servers?.length || 0} server(s)`);
  },

  async 'load-balancers'() {
    const lbs = await requestAll('/load_balancers', 'load_balancers');
    if (!lbs.length) return console.log(`no load balancers in project "${project().name}"`);
    for (const l of lbs) console.log(`${l.name.padEnd(24)} ${l.public_net?.ipv4?.ip || ''} -> ${l.targets?.length || 0} target(s)`);
  },

  async types(args) {
    await loadCurrency();
    const types = await requestAll('/server_types', 'server_types');
    const location = flag(args, 'location', 'hel1');
    const usable = types.filter((t) => !t.deprecated && t.prices?.some((p) => p.location === location));
    console.log(`server sizes available in ${location}   (monthly price, including VAT where it applies)\n`);
    for (const t of usable.sort((a, b) => a.cores - b.cores || a.memory - b.memory)) {
      const price = t.prices.find((p) => p.location === location);
      console.log(`${t.name.padEnd(10)} ${String(t.cores + ' vCPU').padEnd(8)} ${String(t.memory + ' GB').padEnd(8)} ${String(t.disk + ' GB disk').padEnd(13)} ${money(price?.price_monthly?.gross).padEnd(9)} ${t.architecture}`);
    }
    console.log('\nA type is only available where it is listed — sizes differ by location.');
  },

  async locations() {
    const { locations } = await request('/locations');
    for (const l of locations) console.log(`${l.name.padEnd(8)} ${l.city}, ${l.country}${l.network_zone ? `   (network zone ${l.network_zone})` : ''}`);
  },

  async images(args) {
    const images = await requestAll('/images', 'images', { query: { type: flag(args, 'type', 'system'), architecture: flag(args, 'arch', 'x86') } });
    for (const i of images.filter((i) => !i.deprecated)) console.log(`${i.name?.padEnd(22) || String(i.id).padEnd(22)} ${i.description}`);
  },

  async snapshots() {
    const images = await requestAll('/images', 'images', { query: { type: 'snapshot' } });
    if (!images.length) return console.log(`no snapshots in project "${project().name}"`);
    for (const i of images) console.log(`${String(i.id).padEnd(12)} ${String(i.description).padEnd(34)} ${(i.image_size || 0).toFixed(1)} GB   ${String(i.created).slice(0, 10)}`);
  },

  /** What this project is actually costing, which is the question behind "list servers". */
  async costs() {
    await loadCurrency();
    const [servers, volumes, ips, lbs] = await Promise.all([
      requestAll('/servers', 'servers'),
      requestAll('/volumes', 'volumes'),
      requestAll('/primary_ips', 'primary_ips'),
      requestAll('/load_balancers', 'load_balancers'),
    ]);
    let total = 0;
    const line = (what, amount) => { total += amount || 0; console.log(`${what.padEnd(40)} ${money(amount)}/mo`); };

    for (const s of servers) line(`server ${s.name} (${s.server_type.name})`, monthly(s));
    for (const v of volumes) line(`volume ${v.name} (${v.size} GB)`, v.size * 0.0524);
    for (const l of lbs) line(`load balancer ${l.name}`, Number(l.load_balancer_type?.prices?.[0]?.price_monthly?.gross || 0));
    for (const ip of ips.filter((i) => !i.assignee_id)) line(`unassigned ${ip.type} ${ip.ip}`, Number(ip.dns_ptr ? 0.6 : 0.6));

    console.log(`${''.padEnd(40, '-')} ---------`);
    console.log(`${`project "${project().name}"`.padEnd(40)} ${money(total)}/mo`);
    console.log('\nApproximate: volume and IP prices are list rates, and traffic over the included allowance is extra.');
    console.log('Unassigned IP addresses are billed too — they are the usual surprise on a bill.');
  },

  async metrics(args) {
    const s = await findServer(args[0]);
    const type = flag(args, 'type', 'cpu');
    const hours = Number(flag(args, 'hours', 6));
    const end = new Date();
    const start = new Date(end.getTime() - hours * 3600_000);
    const { metrics } = await request(`/servers/${s.id}/metrics`, {
      query: { type, start: start.toISOString(), end: end.toISOString(), step: Math.max(60, (hours * 3600) / 60) },
    });
    for (const [series, values] of Object.entries(metrics.time_series || {})) {
      const numbers = values.values.map((v) => Number(v[1])).filter((n) => !Number.isNaN(n));
      if (!numbers.length) continue;
      const avg = numbers.reduce((a, b) => a + b, 0) / numbers.length;
      console.log(`${series.padEnd(28)} average ${avg.toFixed(1)}   peak ${Math.max(...numbers).toFixed(1)}   over the last ${hours}h`);
    }
    console.log(`\n(types: cpu, disk, network — ${s.name}, project "${project().name}")`);
  },

  // --- DNS ------------------------------------------------------------------

  async zones() {
    const zones = await requestAll('/zones', 'zones');
    if (!zones.length) return console.log(`no DNS zones in project "${project().name}"`);
    for (const z of zones) console.log(`${z.name.padEnd(32)} ${z.status.padEnd(10)} ${z.mode}   ${z.record_count ?? ''} records`);
    console.log('\nA zone only does anything once the domain\'s nameservers point at Hetzner at the registrar.');
  },

  async dns([hostname]) {
    if (!hostname) throw new Error('usage: dns <domain>');
    const zone = await findZone(hostname);
    const rrsets = await requestAll(`/zones/${zone.id}/rrsets`, 'rrsets');
    console.log(`${zone.name} — ${rrsets.length} record sets\n`);
    for (const r of rrsets) {
      const full = r.name === '@' ? zone.name : `${r.name}.${zone.name}`;
      for (const record of r.records || []) {
        console.log(`${r.type.padEnd(6)} ${full.padEnd(38)} ${String(record.value).slice(0, 44).padEnd(46)} ttl ${r.ttl ?? '(zone default)'}`);
      }
    }
  },

  /**
   * Hetzner groups records by name+type into a "record set", where Cloudflare
   * keeps them separate. Adding a second address for the same name means adding
   * to the set, not creating another record — so this reads the set first and
   * replaces it, which is what someone asking to "point app at this server"
   * means.
   */
  async 'dns-add'(args) {
    const [hostname, type, value] = args;
    if (!hostname || !type || !value) throw new Error('usage: dns-add <hostname> <type> <value> [--ttl 300] [--append]');
    const zone = await findZone(hostname);
    const name = relativeName(hostname, zone.name);
    const ttl = Number(flag(args, 'ttl', 0)) || undefined;

    const existing = await request(`/zones/${zone.id}/rrsets/${encodeURIComponent(name)}/${type.toUpperCase()}`)
      .then((p) => p.rrset).catch(() => null);

    if (!existing) {
      await request(`/zones/${zone.id}/rrsets`, {
        method: 'POST',
        body: { name, type: type.toUpperCase(), ttl, records: [{ value }] },
      });
      console.log(`added ${type.toUpperCase()} ${hostname} -> ${value}   (zone ${zone.name}, project "${project().name}")`);
      return;
    }

    const records = args.includes('--append')
      ? [...existing.records.filter((r) => r.value !== value), { value }]
      : [{ value }];
    await request(`/zones/${zone.id}/rrsets/${encodeURIComponent(name)}/${type.toUpperCase()}/actions/set_records`, {
      method: 'POST', body: { records },
    });
    const was = existing.records.map((r) => r.value).join(', ');
    console.log(`${type.toUpperCase()} ${hostname} -> ${records.map((r) => r.value).join(', ')}   (was ${was})`);
  },

  async 'dns-remove'(args) {
    const [hostname] = args;
    const type = flag(args, 'type');
    if (!hostname || !type) throw new Error('usage: dns-remove <hostname> --type A --yes');
    const zone = await findZone(hostname);
    const name = relativeName(hostname, zone.name);
    const rrset = await request(`/zones/${zone.id}/rrsets/${encodeURIComponent(name)}/${type.toUpperCase()}`)
      .then((p) => p.rrset).catch(() => null);

    if (!rrset) return console.log(`no ${type.toUpperCase()} record for ${hostname} in ${zone.name}`);
    for (const r of rrset.records) console.log(`${type.toUpperCase()} ${hostname} -> ${r.value}`);

    if (!args.includes('--yes')) {
      console.log(`\nThis would delete ${rrset.records.length} record(s) in zone ${zone.name}. Re-run with --yes to confirm.`);
      process.exitCode = 1;
      return;
    }
    await request(`/zones/${zone.id}/rrsets/${encodeURIComponent(name)}/${type.toUpperCase()}`, { method: 'DELETE' });
    console.log(`deleted the ${type.toUpperCase()} record for ${hostname}`);
  },

  /** What the world currently sees, asked of public resolvers rather than Hetzner. */
  async check([hostname]) {
    if (!hostname) throw new Error('usage: check <hostname>');
    const { Resolver } = await import('node:dns/promises');
    const resolver = new Resolver();
    resolver.setServers(['1.1.1.1', '8.8.8.8']);
    let found = false;
    for (const type of ['A', 'AAAA', 'CNAME']) {
      try {
        const answers = await resolver.resolve(hostname, type);
        console.log(`${type.padEnd(6)} ${answers.join(', ')}`);
        found = true;
      } catch (err) {
        if (err.code !== 'ENODATA' && err.code !== 'ENOTFOUND') throw err;
      }
    }
    if (!found) console.log(`${hostname} does not resolve yet`);
  },
};

// --- command line -----------------------------------------------------------

const isMain = process.argv[1]?.endsWith('hz.mjs');
if (isMain) {
  const { name: projectName, args: argv } = takeTargetFlag(process.argv.slice(2), SPEC);
  const [command, ...args] = argv;
  const handler = COMMANDS[command];
  if (!handler) {
    console.error(`usage: hz.mjs [--project <name>] <${Object.keys(COMMANDS).join('|')}> [args]`);
    process.exit(2);
  }
  try {
    useProject(projectName);
    await handler(args);
  } catch (err) {
    console.error(err instanceof HetznerError ? err.message : `error: ${err.message}`);
    process.exit(1);
  }
}
