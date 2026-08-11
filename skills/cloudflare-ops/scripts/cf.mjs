#!/usr/bin/env node
// cf.mjs — thin Cloudflare API client plus the everyday read commands.
//
// The token is read from the shared credential store and used in-process. It is
// never printed, never passed on a command line, and never written to a log.

import { readSecrets } from '../lib/store.mjs';

const API = 'https://api.cloudflare.com/client/v4';

// Cloudflare's edge rejects some default runtime User-Agents outright, and the
// resulting 403 looks exactly like a permissions problem. Always send our own.
const USER_AGENT = 'itqan-agent-toolkit/1.0 (+https://github.com/itqanlab/agent-toolkit)';

export class CloudflareError extends Error {
  constructor(message, { status, errors = [] } = {}) {
    super(message);
    this.name = 'CloudflareError';
    this.status = status;
    this.errors = errors;
  }
}

export function getToken({ key = 'CLOUDFLARE_API_TOKEN' } = {}) {
  const token = readSecrets('cloudflare')[key];
  if (!token) {
    throw new CloudflareError(
      'Cloudflare is not connected yet. Run the setup first:\n' +
      '  node scripts/setup.mjs begin',
    );
  }
  return token;
}

/** One call against the Cloudflare API. Returns the parsed envelope. */
export async function request(path, { method = 'GET', body, token, query } = {}) {
  const url = new URL(API + path);
  for (const [k, v] of Object.entries(query || {})) {
    if (v !== undefined && v !== null) url.searchParams.set(k, String(v));
  }

  const response = await fetch(url, {
    method,
    headers: {
      Authorization: `Bearer ${token || getToken()}`,
      'User-Agent': USER_AGENT,
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  const text = await response.text();
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    throw new CloudflareError(`Cloudflare returned a non-JSON response (HTTP ${response.status})`, { status: response.status });
  }

  if (!payload.success) {
    throw new CloudflareError(explain(payload.errors, response.status), {
      status: response.status,
      errors: payload.errors || [],
    });
  }
  return payload;
}

/** Turn Cloudflare's error codes into something a non-engineer can act on. */
function explain(errors = [], status) {
  const first = errors[0];
  if (!first) return `Cloudflare rejected the request (HTTP ${status}).`;

  if (first.code === 10000 || status === 403) {
    return (
      `Cloudflare refused this action: ${first.message}\n` +
      'This usually means the saved token is missing a permission. ' +
      'Re-run the setup to replace it:\n  node scripts/setup.mjs begin --force'
    );
  }
  if (status === 401) {
    return (
      `Cloudflare did not accept the saved token: ${first.message}\n` +
      'It may have been deleted or expired. Re-run:\n  node scripts/setup.mjs begin --force'
    );
  }
  return `${first.message} (code ${first.code})`;
}

/** Follow pagination to the end. */
export async function requestAll(path, options = {}) {
  const results = [];
  for (let page = 1; ; page += 1) {
    const payload = await request(path, { ...options, query: { ...options.query, page, per_page: 50 } });
    results.push(...(payload.result || []));
    const info = payload.result_info;
    if (!info || !info.total_pages || page >= info.total_pages) return results;
  }
}

// --- helpers used by both this file and the playbooks -----------------------

export async function whoami(token) {
  const [accounts, user] = await Promise.all([
    request('/accounts', { token }).then((p) => p.result),
    request('/user', { token }).then((p) => p.result).catch(() => null),
  ]);
  return { accounts, user };
}

/** Resolve a hostname to the zone that serves it, longest match wins. */
export async function findZone(hostname) {
  const zones = await requestAll('/zones');
  const match = zones
    .filter((z) => hostname === z.name || hostname.endsWith(`.${z.name}`))
    .sort((a, b) => b.name.length - a.name.length)[0];
  if (!match) {
    throw new CloudflareError(
      `No Cloudflare zone found for "${hostname}".\n` +
      `The domain must be added to Cloudflare first. Zones on this account: ${zones.map((z) => z.name).join(', ') || '(none)'}`,
    );
  }
  return match;
}

// --- command line -----------------------------------------------------------

const COMMANDS = {
  async whoami() {
    const { accounts, user } = await whoami();
    console.log(`signed in as: ${user?.email || '(token has no user access)'}`);
    for (const a of accounts) console.log(`  account: ${a.name}  (${a.id})`);
  },

  async zones() {
    const zones = await requestAll('/zones');
    if (!zones.length) return console.log('no domains on this account yet');
    for (const z of zones) console.log(`${z.name.padEnd(32)} ${z.status.padEnd(10)} ${z.id}`);
  },

  async dns([hostname]) {
    if (!hostname) throw new Error('usage: dns <domain>');
    const zone = await findZone(hostname);
    const records = await requestAll(`/zones/${zone.id}/dns_records`);
    console.log(`${zone.name} — ${records.length} records\n`);
    for (const r of records) {
      const proxied = r.proxied ? 'proxied' : 'dns-only';
      console.log(`${r.type.padEnd(6)} ${r.name.padEnd(38)} ${String(r.content).slice(0, 40).padEnd(42)} ${proxied}`);
    }
  },

  // dns-add <name> <type> <content> [--proxied] [--ttl 300]
  async 'dns-add'(args) {
    const [name, type, content] = args;
    if (!name || !type || !content) throw new Error('usage: dns-add <name> <type> <content> [--proxied] [--ttl 300]');
    const zone = await findZone(name);
    const ttlIndex = args.indexOf('--ttl');
    const record = await request(`/zones/${zone.id}/dns_records`, {
      method: 'POST',
      body: {
        type: type.toUpperCase(),
        name,
        content,
        proxied: args.includes('--proxied'),
        ttl: ttlIndex === -1 ? 1 : Number(args[ttlIndex + 1]),
      },
    }).then((p) => p.result);
    console.log(`added ${record.type} ${record.name} -> ${record.content} (${record.proxied ? 'proxied' : 'dns-only'})`);
    console.log(`id: ${record.id}`);
  },

  // Destructive, so it refuses to run without --yes. The caller is expected to
  // have shown the user exactly which records match first.
  async 'dns-remove'(args) {
    const [name] = args;
    if (!name) throw new Error('usage: dns-remove <name> [--type A] --yes');
    const typeIndex = args.indexOf('--type');
    const zone = await findZone(name);
    const matches = (await requestAll(`/zones/${zone.id}/dns_records`, { query: { name } }))
      .filter((r) => typeIndex === -1 || r.type === args[typeIndex + 1]?.toUpperCase());

    if (!matches.length) return console.log(`no records found for ${name}`);
    for (const r of matches) console.log(`${r.type} ${r.name} -> ${r.content}`);

    if (!args.includes('--yes')) {
      console.log(`\n${matches.length} record(s) would be deleted. Re-run with --yes to confirm.`);
      process.exitCode = 1;
      return;
    }
    for (const r of matches) {
      await request(`/zones/${zone.id}/dns_records/${r.id}`, { method: 'DELETE' });
      console.log(`deleted ${r.type} ${r.name}`);
    }
  },

  // Ask a public resolver what the world currently sees. Uses Node's own DNS
  // client rather than `dig`, which is not present on a default Windows install.
  async check([hostname]) {
    if (!hostname) throw new Error('usage: check <hostname>');
    const { Resolver } = await import('node:dns/promises');
    const resolver = new Resolver();
    resolver.setServers(['1.1.1.1', '8.8.8.8']);
    for (const type of ['A', 'AAAA', 'CNAME']) {
      try {
        const answers = await resolver.resolve(hostname, type);
        console.log(`${type.padEnd(6)} ${answers.join(', ')}`);
      } catch (err) {
        if (err.code !== 'ENODATA' && err.code !== 'ENOTFOUND') throw err;
      }
    }
  },

  async pages() {
    const { accounts } = await whoami();
    for (const account of accounts) {
      const projects = await request(`/accounts/${account.id}/pages/projects`).then((p) => p.result);
      console.log(`${account.name}: ${projects.length} Pages projects`);
      for (const p of projects) console.log(`  ${p.name.padEnd(28)} ${(p.domains || []).join(', ')}`);
    }
  },

  async r2() {
    const { accounts } = await whoami();
    for (const account of accounts) {
      const { buckets = [] } = await request(`/accounts/${account.id}/r2/buckets`).then((p) => p.result);
      console.log(`${account.name}: ${buckets.length} R2 buckets`);
      for (const b of buckets) console.log(`  ${b.name}`);
    }
  },
};

const isMain = process.argv[1]?.endsWith('cf.mjs');
if (isMain) {
  const [command, ...args] = process.argv.slice(2);
  const handler = COMMANDS[command];
  if (!handler) {
    console.error(`usage: cf.mjs <${Object.keys(COMMANDS).join('|')}> [args]`);
    process.exit(2);
  }
  try {
    await handler(args);
  } catch (err) {
    console.error(err instanceof CloudflareError ? err.message : `error: ${err.message}`);
    process.exit(1);
  }
}
