#!/usr/bin/env node
// dk.mjs — thin Dokploy API client plus the everyday commands.
//
// The key is read from the shared credential store and used in-process. It is
// never printed, never passed on a command line, and never written to a log.
//
// Three things shape everything here:
//
//   1. Dokploy is self-hosted, so there is no single address to talk to. Every
//      instance is a different URL, which is why a target here is a URL *and* a
//      key, and why the same person often has several.
//   2. The API is one flat namespace of "router.procedure" calls — reads are GET
//      with query parameters, writes are POST with a JSON body. There are no
//      REST paths to reason about, so this file maps human words onto them.
//   3. Nothing is addressed by name. Every call wants an id, and ids are not
//      shown anywhere in the interface a user knows. So almost every command
//      starts by finding a service by the name the user actually calls it.

import { resolveTarget, takeTargetFlag } from '../lib/targets.mjs';

const USER_AGENT = 'itqan-agent-toolkit/1.0 (+https://github.com/itqanlab/agent-toolkit)';

export const SPEC = {
  provider: 'dokploy',
  label: 'Dokploy instance',
  prefix: 'DOKPLOY',
  flag: 'instance',
  fields: { url: 'DOKPLOY_URL', key: 'DOKPLOY_API_KEY' },
};

/**
 * The kinds of thing Dokploy can run, and the names it uses for each in the API.
 * `list` is where they appear inside an environment; `router` and `id` are how
 * they are addressed afterwards. Everything else in this file is written against
 * this table rather than against applications specifically, so a database gets
 * the same commands a web app does.
 */
const KINDS = [
  { list: 'applications', router: 'application', id: 'applicationId', what: 'app' },
  { list: 'compose', router: 'compose', id: 'composeId', what: 'compose' },
  { list: 'postgres', router: 'postgres', id: 'postgresId', what: 'postgres' },
  { list: 'mysql', router: 'mysql', id: 'mysqlId', what: 'mysql' },
  { list: 'mariadb', router: 'mariadb', id: 'mariadbId', what: 'mariadb' },
  { list: 'mongo', router: 'mongo', id: 'mongoId', what: 'mongo' },
  { list: 'redis', router: 'redis', id: 'redisId', what: 'redis' },
  { list: 'libsql', router: 'libsql', id: 'libsqlId', what: 'libsql' },
];

export class DokployError extends Error {
  constructor(message, { status } = {}) {
    super(message);
    this.name = 'DokployError';
    this.status = status;
  }
}

let current = null;

export function useInstance(name) {
  current = resolveTarget(SPEC, name);
  return current;
}

export function instance() {
  if (!current) current = resolveTarget(SPEC, '');
  return current;
}

/** Trailing slashes and a pasted-in "/api" are both common; neither should break anything. */
function baseUrl() {
  const raw = String(instance().fields.url || '').trim().replace(/\/+$/, '');
  if (!raw) throw new DokployError('No Dokploy address saved. Run:  node scripts/setup.mjs add <a-name-for-it>');
  return raw.replace(/\/api$/, '') + '/api';
}

/** One call against a Dokploy instance. */
export async function request(procedure, { method = 'GET', body, query } = {}) {
  const url = new URL(`${baseUrl()}/${procedure.replace(/^\//, '')}`);
  for (const [k, v] of Object.entries(query || {})) {
    if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, String(v));
  }

  let response;
  for (let attempt = 1; ; attempt += 1) {
    try {
      response = await fetch(url, {
        method,
        headers: {
          // Dokploy wants x-api-key. A bearer token is rejected outright, which
          // is worth knowing before debugging a 401 that looks like a bad key.
          'x-api-key': instance().fields.key,
          'User-Agent': USER_AGENT,
          ...(body ? { 'Content-Type': 'application/json' } : {}),
        },
        body: body ? JSON.stringify(body) : undefined,
      });
      break;
    } catch (err) {
      if (attempt >= 3) throw new DokployError(unreachable(err));
      await new Promise((r) => setTimeout(r, attempt * 500));
    }
  }

  const text = await response.text();
  if (!response.ok) throw new DokployError(explain(response.status, text));
  if (!text.trim()) return null;
  try {
    return JSON.parse(text);
  } catch {
    // An HTML body from a URL that should return JSON almost always means the
    // address points at something that is not a Dokploy instance.
    if (/^\s*</.test(text)) {
      throw new DokployError(
        `${instance().fields.url} answered with a web page rather than data.\n` +
        `Check that this is the address of the Dokploy dashboard itself, not a site it hosts:\n` +
        `  node scripts/setup.mjs add ${instance().name} --force`,
      );
    }
    throw new DokployError(`Dokploy returned something unreadable (HTTP ${response.status})`);
  }
}

function unreachable(err) {
  const where = instance().fields.url;
  return (
    `Could not reach ${where} (${err.message}).\n\n` +
    'A self-hosted Dokploy is only reachable when its server is up and the address resolves.\n' +
    'Worth checking, in order: is the address right, is the server running, and is this machine\n' +
    'on a network that can see it — some installations are only reachable over a VPN.'
  );
}

function explain(status, text) {
  const where = `"${instance().name}" (${instance().fields.url})`;
  let message = text;
  try {
    message = JSON.parse(text).message || text;
  } catch { /* keep the raw text */ }

  if (status === 401 || status === 403) {
    return (
      `${where} did not accept the saved key.\n` +
      'Keys are revoked from the dashboard and can also be lost when an instance is reinstalled.\n' +
      `Replace it with:  node scripts/setup.mjs add ${instance().name} --force`
    );
  }
  if (status === 404) return `${where} has no such thing: ${String(message).slice(0, 200)}`;
  if (status === 502 || status === 503 || status === 504) {
    return `${where} is not answering properly (HTTP ${status}). The instance is probably restarting or overloaded.`;
  }
  return `${where} rejected the request (HTTP ${status}): ${String(message).slice(0, 300)}`;
}

// --- finding things ----------------------------------------------------------

/** Every service on the instance, flattened, with where it lives. */
export async function allServices() {
  const projects = await request('project.all');
  const out = [];
  for (const project of projects || []) {
    for (const environment of project.environments || []) {
      for (const kind of KINDS) {
        for (const service of environment[kind.list] || []) {
          out.push({
            kind,
            id: service[kind.id],
            name: service.name,
            status: service.applicationStatus || service.composeStatus || service.status || 'unknown',
            project: project.name,
            projectId: project.projectId,
            environment: environment.name,
          });
        }
      }
    }
  }

  // Databases come back from this call as a bare id — no name, no state. Showing
  // someone a row of blanks where their database should be is worse than the
  // extra call it takes to go and ask, so fill those in.
  const thin = out.filter((s) => !s.name);
  await Promise.all(thin.map(async (service) => {
    const detail = await request(`${service.kind.router}.one`, { query: { [service.kind.id]: service.id } }).catch(() => null);
    service.name = detail?.name || `${service.kind.what}-${String(service.id).slice(0, 6)}`;
    service.status = detail?.applicationStatus || detail?.databaseStatus || service.status;
  }));

  return out;
}

/**
 * Find one service by the name a person calls it.
 *
 * Names are only unique within an environment, so "web" may exist three times.
 * Rather than picking one, this says which ones matched and how to disambiguate
 * — deploying the wrong "web" is not a recoverable mistake.
 */
export async function findService(name, { project } = {}) {
  const services = await allServices();
  const candidates = services.filter((s) => s.name === name && (!project || s.project === project));

  if (candidates.length === 1) return candidates[0];
  if (!candidates.length) {
    const near = services.filter((s) => s.name.toLowerCase().includes(String(name).toLowerCase()));
    throw new DokployError(
      `Nothing called "${name}" on "${instance().name}".\n` +
      (near.length
        ? `Did you mean: ${near.map((s) => `${s.name} (in ${s.project})`).join(', ')}`
        : `Everything here:\n${services.map((s) => `  ${s.name}  —  ${s.project} / ${s.environment}`).join('\n') || '  (nothing yet)'}`),
    );
  }
  throw new DokployError(
    `"${name}" exists in more than one place on "${instance().name}":\n` +
    candidates.map((s) => `  ${s.project} / ${s.environment}  (${s.kind.what})`).join('\n') +
    `\n\nSay which one with  --in <project>`,
  );
}

const flag = (args, name, fallback) => {
  const at = args.indexOf(`--${name}`);
  return at === -1 ? fallback : args[at + 1];
};

const firstLine = (text, width = 60) => {
  const line = String(text || '').split('\n')[0].trim();
  return line.length > width ? `${line.slice(0, width - 1)}…` : line;
};

const ago = (iso) => {
  if (!iso) return '';
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  if (minutes < 1440) return `${Math.round(minutes / 60)}h ago`;
  return `${Math.round(minutes / 1440)}d ago`;
};

/**
 * Dokploy uses one set of words for two different questions, and they do not
 * mean the same thing. On a service, "done" means the last deployment finished,
 * so the thing is up. On a deployment, "done" means that build succeeded. Using
 * one translation for both produces a list of deployments that all claim to be
 * "running", which is nonsense.
 */
const SERVICE_STATE = { done: 'running', running: 'deploying now', error: 'FAILED', idle: 'never deployed' };
const DEPLOY_STATE = { done: 'succeeded', running: 'in progress', error: 'FAILED', idle: 'queued' };

const state = (status) => SERVICE_STATE[status] || status || 'unknown';
const deployState = (status) => DEPLOY_STATE[status] || status || 'unknown';

/** Deployments are listed per kind: compose has its own call. */
async function deploymentsOf(service, { limit = 10 } = {}) {
  const procedure = service.kind.router === 'compose' ? 'deployment.allByCompose' : 'deployment.all';
  const list = await request(procedure, { query: { [service.kind.id]: service.id } });
  return (list || []).slice(0, limit);
}

/**
 * Start a deployment and stay with it until it finishes.
 *
 * The API answers as soon as the job is queued, and a queued build is not a
 * working site. Someone who is told "deployed" and then finds the old version
 * still up has been misled, so this follows the deployment to its end and
 * reports what actually happened — including the error, when there is one.
 */
async function deployAndWatch(service, procedure) {
  const before = await deploymentsOf(service, { limit: 1 });
  const previous = before[0]?.deploymentId;

  await request(procedure, { method: 'POST', body: { [service.kind.id]: service.id } });
  console.log(`deploying ${service.name} on "${instance().name}" (${service.project} / ${service.environment})...`);

  const started = Date.now();
  let latest = null;
  while (Date.now() - started < 20 * 60_000) {
    await new Promise((r) => setTimeout(r, 4000));
    const [top] = await deploymentsOf(service, { limit: 1 });
    if (!top || top.deploymentId === previous) continue;
    latest = top;
    if (top.status !== 'running') break;
    process.stderr.write(`\r  building... ${Math.round((Date.now() - started) / 1000)}s   `);
  }
  process.stderr.write('\r                                   \r');

  if (!latest) {
    console.log('Dokploy accepted the request but has not started a build yet. Check with:');
    console.log(`  node scripts/dk.mjs deployments ${service.name}`);
    return;
  }
  if (latest.status === 'error') {
    console.error(`\nThe deployment FAILED after ${Math.round((Date.now() - started) / 1000)}s.`);
    if (latest.errorMessage) console.error(`\n${String(latest.errorMessage).slice(0, 600)}`);
    console.error(`\nFull build output:  node scripts/dk.mjs build-log ${service.name}`);
    process.exitCode = 1;
    return;
  }
  console.log(`\n${service.name} is deployed and running (${Math.round((Date.now() - started) / 1000)}s).`);
  const domains = await request('domain.byApplicationId', { query: { applicationId: service.id } }).catch(() => []);
  for (const d of domains || []) console.log(`  ${d.https ? 'https' : 'http'}://${d.host}${d.path && d.path !== '/' ? d.path : ''}`);
}

// --- commands ---------------------------------------------------------------

const COMMANDS = {
  async whoami() {
    const [version, projects] = await Promise.all([
      request('settings.getDokployVersion').catch(() => null),
      request('project.all').catch(() => []),
    ]);
    const services = await allServices().catch(() => []);
    console.log(`instance: ${instance().name}`);
    console.log(`address:  ${instance().fields.url}`);
    console.log(`version:  ${version || '(not reported)'}`);
    console.log(`holds:    ${(projects || []).length} project(s), ${services.length} service(s)`);
  },

  async projects() {
    const projects = await request('project.all');
    if (!projects?.length) return console.log(`no projects on "${instance().name}" yet`);
    for (const project of projects) {
      console.log(`\n${project.name}${project.description ? `   — ${project.description}` : ''}`);
      for (const environment of project.environments || []) {
        const services = KINDS.flatMap((kind) => (environment[kind.list] || []).map((s) => ({ kind, s })));
        console.log(`  ${environment.name}${environment.isDefault ? ' (default)' : ''}   ${services.length} service(s)`);
        for (const { kind, s } of services) {
          const name = s.name || `${kind.what} ${String(s[kind.id]).slice(0, 6)}`;
          console.log(`    ${String(name).padEnd(24)} ${kind.what.padEnd(9)} ${state(s.applicationStatus || s.composeStatus || 'unknown')}`);
        }
      }
    }
  },

  /** The flat view: everything on the instance, worst news first. */
  async services() {
    const services = await allServices();
    if (!services.length) return console.log(`nothing deployed on "${instance().name}" yet`);
    const rank = { error: 0, idle: 1, running: 2, done: 3 };
    for (const s of services.sort((a, b) => (rank[a.status] ?? 9) - (rank[b.status] ?? 9))) {
      console.log(`${String(s.name).padEnd(24)} ${String(state(s.status)).padEnd(15)} ${s.kind.what.padEnd(9)} ${s.project} / ${s.environment}`);
    }
    const broken = services.filter((s) => s.status === 'error');
    if (broken.length) console.log(`\n${broken.length} service(s) failed their last deployment: ${broken.map((s) => s.name).join(', ')}`);
  },

  async service(args) {
    const service = await findService(args[0], { project: flag(args, 'in') });
    const detail = await request(`${service.kind.router}.one`, { query: { [service.kind.id]: service.id } });

    console.log(`${service.name}   ${state(service.status)}`);
    console.log(`  where:    ${instance().name} — ${service.project} / ${service.environment}`);
    console.log(`  kind:     ${service.kind.what}`);
    if (detail?.sourceType) {
      const repo = detail.repository || detail.customGitUrl || detail.dockerImage || '';
      console.log(`  source:   ${detail.sourceType}${repo ? ` — ${detail.owner ? `${detail.owner}/` : ''}${repo}` : ''}${detail.branch ? ` (${detail.branch})` : ''}`);
      console.log(`  on push:  ${detail.autoDeploy ? 'deploys automatically' : 'manual deploys only'}`);
    }
    for (const d of detail?.domains || []) console.log(`  address:  ${d.https ? 'https' : 'http'}://${d.host}`);

    const deployments = await deploymentsOf(service, { limit: 1 }).catch(() => []);
    if (deployments[0]) {
      console.log(`  last:     build ${deployState(deployments[0].status)} ${ago(deployments[0].createdAt)} — ${firstLine(deployments[0].title)}`);
    }
    if (detail?.env !== undefined) {
      const keys = String(detail.env || '').split('\n').map((l) => l.split('=')[0].trim()).filter((k) => k && !k.startsWith('#'));
      console.log(`  settings: ${keys.length} environment variable(s) — names only:  node scripts/dk.mjs env ${service.name}`);
    }
  },

  async deploy(args) {
    const service = await findService(args[0], { project: flag(args, 'in') });
    await deployAndWatch(service, `${service.kind.router}.deploy`);
  },

  /** Rebuild from scratch — the answer when a deploy "worked" but shipped stale content. */
  async redeploy(args) {
    const service = await findService(args[0], { project: flag(args, 'in') });
    await deployAndWatch(service, `${service.kind.router}.redeploy`);
  },

  async stop(args) {
    const service = await findService(args[0], { project: flag(args, 'in') });
    if (!args.includes('--yes')) {
      console.log(`${service.name} is ${state(service.status)} in ${service.project} / ${service.environment} on "${instance().name}".`);
      console.log('\nStopping takes it offline. Anything pointing at it will fail until it is started again.');
      console.log(`\nTo go ahead:  node scripts/dk.mjs stop ${service.name} --yes`);
      process.exitCode = 1;
      return;
    }
    await request(`${service.kind.router}.stop`, { method: 'POST', body: { [service.kind.id]: service.id } });
    console.log(`${service.name} is stopping on "${instance().name}"`);
  },

  async start(args) {
    const service = await findService(args[0], { project: flag(args, 'in') });
    await request(`${service.kind.router}.start`, { method: 'POST', body: { [service.kind.id]: service.id } });
    console.log(`${service.name} is starting on "${instance().name}"`);
  },

  /** Restart the container without rebuilding it. */
  async restart(args) {
    const service = await findService(args[0], { project: flag(args, 'in') });
    await request(`${service.kind.router}.reload`, {
      method: 'POST',
      body: { [service.kind.id]: service.id, appName: service.name },
    });
    console.log(`${service.name} is restarting on "${instance().name}" (the running version, not a rebuild)`);
  },

  /** What the application is printing right now. */
  async logs(args) {
    const service = await findService(args[0], { project: flag(args, 'in') });
    const lines = await request(`${service.kind.router}.readLogs`, {
      query: { [service.kind.id]: service.id, tail: flag(args, 'tail', '200'), search: flag(args, 'search') },
    });
    const text = Array.isArray(lines) ? lines.join('\n') : String(lines ?? '');
    console.log(text.trim() || `${service.name} has produced no output — it may not be running.`);
  },

  async deployments(args) {
    const service = await findService(args[0], { project: flag(args, 'in') });
    const list = await deploymentsOf(service, { limit: Number(flag(args, 'limit', 10)) });
    if (!list.length) return console.log(`${service.name} has never been deployed`);
    for (const d of list) {
      console.log(`${deployState(d.status).padEnd(15)} ${ago(d.createdAt).padEnd(10)} ${firstLine(d.title)}`);
      if (d.status === 'error' && d.errorMessage) console.log(`                 ${firstLine(d.errorMessage, 90)}`);
    }
  },

  /** The build output of the last deployment — where a failure actually explains itself. */
  async 'build-log'(args) {
    const service = await findService(args[0], { project: flag(args, 'in') });
    const [latest] = await deploymentsOf(service, { limit: 1 });
    if (!latest) return console.log(`${service.name} has never been deployed`);
    const log = await request('deployment.readLogs', {
      query: { deploymentId: latest.deploymentId, tail: flag(args, 'tail', '400') },
    });
    console.log(Array.isArray(log) ? log.join('\n') : String(log ?? '(no output)'));
  },

  async domains(args) {
    const service = await findService(args[0], { project: flag(args, 'in') });
    const procedure = service.kind.router === 'compose' ? 'domain.byComposeId' : 'domain.byApplicationId';
    const domains = await request(procedure, { query: { [service.kind.id]: service.id } });
    if (!domains?.length) return console.log(`${service.name} has no domain — it is only reachable inside the server`);
    for (const d of domains) {
      console.log(`${d.https ? 'https' : 'http'}://${d.host}${d.path && d.path !== '/' ? d.path : ''}   -> port ${d.port}   ${d.certificateType || 'no certificate'}`);
    }
    console.log('\nA domain only works once its DNS record points at this server.');
  },

  /**
   * Environment variables, names only.
   *
   * These are where the passwords live. Printing them puts every secret an
   * application holds into a transcript, so the default is names alone and
   * asking for more is a deliberate act.
   */
  async env(args) {
    const service = await findService(args[0], { project: flag(args, 'in') });
    const detail = await request(`${service.kind.router}.one`, { query: { [service.kind.id]: service.id } });
    const lines = String(detail?.env || '').split('\n').map((l) => l.trim()).filter((l) => l && !l.startsWith('#'));
    if (!lines.length) return console.log(`${service.name} has no environment variables set`);

    for (const line of lines) {
      const key = line.split('=')[0];
      const value = line.slice(key.length + 1);
      console.log(args.includes('--values') ? line : `${key.padEnd(32)} (${value.length} characters)`);
    }
    if (!args.includes('--values')) {
      console.log('\nValues are hidden — these are usually passwords and keys. Add --values to print them,');
      console.log('but only into a terminal nobody is watching and nothing is recording.');
    }
  },

  async containers(args) {
    const containers = await request('docker.getContainers', { query: { serverId: flag(args, 'server') } });
    if (!containers?.length) return console.log('no containers running');
    for (const c of containers) {
      console.log(`${String(c.name).padEnd(40)} ${String(c.state).padEnd(10)} ${String(c.status || '').slice(0, 24).padEnd(26)} ${c.image || ''}`);
    }
  },

  /** Is the instance itself healthy — as opposed to one thing on it. */
  async health() {
    const [health, servers] = await Promise.all([
      request('settings.checkInfrastructureHealth').catch(() => null),
      request('server.all').catch(() => []),
    ]);
    if (health) {
      for (const [name, value] of Object.entries(health)) {
        console.log(`${String(name).padEnd(24)} ${typeof value === 'object' ? JSON.stringify(value) : value}`);
      }
    }
    for (const s of servers || []) {
      console.log(`server ${String(s.name).padEnd(20)} ${s.ipAddress}   ${s.serverStatus || ''}`);
    }
    const broken = (await allServices()).filter((s) => s.status === 'error');
    console.log(broken.length
      ? `\n${broken.length} service(s) failed their last deployment: ${broken.map((s) => s.name).join(', ')}`
      : '\nEvery service deployed successfully last time it was tried.');
  },

  async servers() {
    const servers = await request('server.all');
    if (!servers?.length) {
      return console.log(`"${instance().name}" runs everything on the machine Dokploy itself is installed on.`);
    }
    for (const s of servers) console.log(`${String(s.name).padEnd(24)} ${s.ipAddress}   ${s.serverStatus || ''}`);
  },
};

// --- command line -----------------------------------------------------------

const isMain = process.argv[1]?.endsWith('dk.mjs');
if (isMain) {
  const { name: instanceName, args: argv } = takeTargetFlag(process.argv.slice(2), SPEC);
  const [command, ...args] = argv;
  const handler = COMMANDS[command];
  if (!handler) {
    console.error(`usage: dk.mjs [--instance <name>] <${Object.keys(COMMANDS).join('|')}> [args]`);
    process.exit(2);
  }
  try {
    useInstance(instanceName);
    await handler(args);
  } catch (err) {
    console.error(err instanceof DokployError ? err.message : `error: ${err.message}`);
    process.exit(1);
  }
}
