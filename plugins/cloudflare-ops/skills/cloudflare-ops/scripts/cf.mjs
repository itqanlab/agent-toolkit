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

  const init = {
    method,
    headers: {
      Authorization: `Bearer ${token || getToken()}`,
      'User-Agent': USER_AGENT,
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  };

  // A dropped connection surfaces as a bare "fetch failed", which tells the
  // person nothing. Retry the transient case, then say something useful.
  let response;
  for (let attempt = 1; ; attempt += 1) {
    try {
      response = await fetch(url, init);
      break;
    } catch (err) {
      if (attempt >= 3) {
        throw new CloudflareError(
          `Could not reach Cloudflare (${err.message}). Check the internet connection and try again.`,
        );
      }
      await new Promise((resolve) => setTimeout(resolve, attempt * 500));
    }
  }

  const text = await response.text();

  // Some endpoints — several DELETEs among them — answer with an empty body.
  // That is a success, not a malformed response.
  if (!text.trim()) {
    if (response.ok) return { success: true, result: null, errors: [], messages: [] };
    throw new CloudflareError(`Cloudflare rejected the request (HTTP ${response.status}).`, { status: response.status });
  }

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

/** Most people have one account; commands that need an id should not ask for it. */
export async function firstAccountId() {
  const { accounts } = await whoami();
  if (!accounts.length) throw new CloudflareError('This token cannot see any Cloudflare account.');
  return accounts[0].id;
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

  // pages-create <name> [--branch main]
  async 'pages-create'(args) {
    const [name] = args;
    if (!name) throw new Error('usage: pages-create <project-name> [--branch main]');
    const branchIndex = args.indexOf('--branch');
    const accountId = await firstAccountId();
    const project = await request(`/accounts/${accountId}/pages/projects`, {
      method: 'POST',
      body: { name, production_branch: branchIndex === -1 ? 'main' : args[branchIndex + 1] },
    }).then((p) => p.result);
    console.log(`created Pages project ${project.name}`);
    console.log(`it will be served at https://${project.subdomain}`);
    console.log(`\nnext: put your built files online with`);
    console.log(`  node scripts/cf.mjs pages-deploy ${project.name} ./dist`);
  },

  async 'pages-domains'([name]) {
    if (!name) throw new Error('usage: pages-domains <project-name>');
    const accountId = await firstAccountId();
    const domains = await request(`/accounts/${accountId}/pages/projects/${name}/domains`).then((p) => p.result);
    if (!domains.length) return console.log(`${name} has no custom domains`);
    for (const d of domains) console.log(`${d.name.padEnd(36)} ${d.status}`);
  },

  /**
   * Attach a custom domain to a Pages project AND create the DNS record it needs.
   * Doing only one of the two leaves the domain stuck "pending", which is the
   * single most common way this goes wrong.
   */
  async 'pages-domain'(args) {
    const [name, hostname] = args;
    if (!name || !hostname) throw new Error('usage: pages-domain <project-name> <hostname>');
    const accountId = await firstAccountId();

    const project = await request(`/accounts/${accountId}/pages/projects/${name}`).then((p) => p.result);
    const target = project.subdomain;

    await request(`/accounts/${accountId}/pages/projects/${name}/domains`, {
      method: 'POST',
      body: { name: hostname },
    });
    console.log(`attached ${hostname} to Pages project ${name}`);

    // Pages custom domains must be proxied — Cloudflare has to be in the path to
    // serve the site and its certificate. This is not the usual optional choice.
    const zone = await findZone(hostname);
    const existing = (await requestAll(`/zones/${zone.id}/dns_records`, { query: { name: hostname } }));
    for (const r of existing) {
      await request(`/zones/${zone.id}/dns_records/${r.id}`, { method: 'DELETE' });
      console.log(`removed old ${r.type} record for ${hostname}`);
    }
    await request(`/zones/${zone.id}/dns_records`, {
      method: 'POST',
      body: { type: 'CNAME', name: hostname, content: target, proxied: true, ttl: 1 },
    });
    console.log(`pointed ${hostname} -> ${target} (proxied)`);
    console.log(`\nthe certificate is issued automatically and usually takes a minute or two`);
    console.log(`check with:  node scripts/cf.mjs pages-domains ${name}`);
  },

  /**
   * Upload a built directory. This is the one thing the API cannot do for us —
   * the files are on this machine — so it hands off to Cloudflare's own tool,
   * run through npx so there is nothing extra to install. The stored token is
   * passed in the environment, so wrangler needs no separate login.
   */
  async 'pages-deploy'(args) {
    const [name, dir] = args;
    if (!name || !dir) throw new Error('usage: pages-deploy <project-name> <directory>');
    const { existsSync } = await import('node:fs');
    if (!existsSync(dir)) throw new Error(`directory not found: ${dir}\nBuild the site first, then point at its output folder.`);

    const accountId = await firstAccountId();
    const { spawnSync } = await import('node:child_process');
    const branchIndex = args.indexOf('--branch');

    console.log(`uploading ${dir} to Pages project ${name}...\n`);
    const result = spawnSync(
      process.platform === 'win32' ? 'npx.cmd' : 'npx',
      ['--yes', 'wrangler@latest', 'pages', 'deploy', dir, '--project-name', name,
        // Without this, wrangler warns whenever the working tree is dirty. That
        // is normal here: we are uploading a built directory, not a git deploy.
        '--commit-dirty=true',
        ...(branchIndex === -1 ? [] : ['--branch', args[branchIndex + 1]])],
      {
        stdio: 'inherit',
        env: { ...process.env, CLOUDFLARE_API_TOKEN: getToken(), CLOUDFLARE_ACCOUNT_ID: accountId },
      },
    );
    if (result.error) {
      throw new Error(
        `could not run wrangler: ${result.error.message}\n` +
        'It is downloaded on demand through npx, which needs network access the first time.',
      );
    }
    if (result.status !== 0) process.exit(result.status ?? 1);
    console.log(`\nto put your own domain on it:`);
    console.log(`  node scripts/cf.mjs pages-domain ${name} www.example.com`);
  },

  async workers() {
    const accountId = await firstAccountId();
    const [scripts, domains] = await Promise.all([
      request(`/accounts/${accountId}/workers/scripts`).then((p) => p.result),
      request(`/accounts/${accountId}/workers/domains`).then((p) => p.result).catch(() => []),
    ]);
    if (!scripts.length) return console.log('no Workers on this account yet');
    for (const s of scripts) {
      const hosts = domains.filter((d) => d.service === s.id).map((d) => d.hostname);
      console.log(`${s.id.padEnd(32)} ${hosts.join(', ') || `${s.id}.<your-subdomain>.workers.dev`}`);
    }
  },

  async 'worker-domains'() {
    const accountId = await firstAccountId();
    const domains = await request(`/accounts/${accountId}/workers/domains`).then((p) => p.result);
    if (!domains.length) return console.log('no Worker custom domains');
    for (const d of domains) console.log(`${d.hostname.padEnd(36)} -> ${d.service} (${d.environment})`);
  },

  /**
   * Upload a Worker. Same hand-off as pages-deploy and for the same reason: the
   * code is on this machine. wrangler reads its configuration from the directory,
   * so it runs there rather than wherever this was invoked from.
   */
  async 'worker-deploy'(args) {
    const dir = args[0] || '.';
    const { existsSync, readFileSync } = await import('node:fs');
    const { join } = await import('node:path');
    if (!existsSync(dir)) throw new Error(`directory not found: ${dir}`);

    const hasConfig = ['wrangler.toml', 'wrangler.json', 'wrangler.jsonc']
      .some((f) => existsSync(join(dir, f)));
    if (!hasConfig) {
      throw new Error(
        `no wrangler configuration in ${dir}\n` +
        'A Worker needs a wrangler.toml (or wrangler.json) next to its code, naming the\n' +
        'worker and its entry file. Create one, or point at the directory that has it.',
      );
    }

    const accountId = await firstAccountId();

    // A brand new account has no workers.dev subdomain, and wrangler responds by
    // trying to register one named after the current directory — which usually
    // fails, with an error that sends you to the dashboard and explains nothing.
    // Catch it here, where we can say what to actually do.
    const config = ['wrangler.toml', 'wrangler.json', 'wrangler.jsonc']
      .map((f) => join(dir, f)).filter(existsSync).map((f) => readFileSync(f, 'utf8')).join('\n');
    const optedOut = /workers_dev\s*[=:]\s*false/.test(config);

    if (!optedOut) {
      const hasSubdomain = await request(`/accounts/${accountId}/workers/subdomain`)
        .then(() => true).catch(() => false);
      if (!hasSubdomain) {
        throw new CloudflareError(
          'This account has no workers.dev subdomain yet, so the deploy would fail.\n\n' +
          'Two ways forward:\n\n' +
          '  1. If this Worker will live on your own domain (recommended), add this line\n' +
          `     to the wrangler config in ${dir} and run this again:\n\n` +
          '         workers_dev = false\n\n' +
          '     Then attach the hostname with:\n' +
          '         node scripts/cf.mjs worker-domain <worker-name> api.example.com\n\n' +
          '  2. Otherwise open the Workers page in the Cloudflare dashboard once — just\n' +
          '     visiting it creates the subdomain — then run this again:\n' +
          '         https://dash.cloudflare.com/?to=/:account/workers/workers-and-pages',
        );
      }
    }

    const { spawnSync } = await import('node:child_process');
    console.log(`deploying the Worker in ${dir}...\n`);
    const result = spawnSync(
      process.platform === 'win32' ? 'npx.cmd' : 'npx',
      ['--yes', 'wrangler@latest', 'deploy'],
      {
        cwd: dir,
        stdio: 'inherit',
        env: { ...process.env, CLOUDFLARE_API_TOKEN: getToken(), CLOUDFLARE_ACCOUNT_ID: accountId },
      },
    );
    if (result.error) {
      throw new Error(
        `could not run wrangler: ${result.error.message}\n` +
        'It is downloaded on demand through npx, which needs network access the first time.',
      );
    }
    if (result.status !== 0) process.exit(result.status ?? 1);
    console.log(`\nto put your own domain on it:`);
    console.log(`  node scripts/cf.mjs worker-domain <worker-name> api.example.com`);
  },

  /**
   * Attach a hostname to a Worker. Cloudflare creates the DNS record itself for
   * this one — unlike Pages — so adding a record by hand here would conflict.
   */
  async 'worker-domain'(args) {
    const [service, hostname] = args;
    if (!service || !hostname) throw new Error('usage: worker-domain <worker-name> <hostname>');
    const envIndex = args.indexOf('--env');
    const accountId = await firstAccountId();
    const zone = await findZone(hostname);

    const domain = await request(`/accounts/${accountId}/workers/domains`, {
      method: 'PUT',
      body: {
        hostname,
        service,
        environment: envIndex === -1 ? 'production' : args[envIndex + 1],
        zone_id: zone.id,
      },
    }).then((p) => p.result);

    console.log(`${domain.hostname} now routes to the Worker "${domain.service}"`);
    console.log('Cloudflare manages the DNS record and the certificate for this hostname itself.');
    console.log(`\ncheck with:  node scripts/cf.mjs check ${hostname}`);
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
