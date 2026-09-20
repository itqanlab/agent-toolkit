#!/usr/bin/env node
// api.mjs — search Hetzner's API description offline.
//
// The wrapped commands in hz.mjs cover the everyday work. For anything else the
// question is always the same: which endpoint, and what does it want in the body?
// Guessing produces confident, wrong code. This answers it from Hetzner's own
// OpenAPI description, cached next to the credentials.
//
//   api.mjs search <words...>     find endpoints
//   api.mjs show <path> [method]  parameters and request body for one endpoint
//   api.mjs refresh               re-download the description
//
// Pair it with request() from hz.mjs, which already reaches every endpoint with
// the saved token for whichever project is selected.

import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { storeRoot } from '../lib/store.mjs';

const SPEC_URL = 'https://docs.hetzner.cloud/cloud.spec.json';
const SPEC_PATH = join(storeRoot(), 'cache', 'hetzner-openapi.json');
const STALE_AFTER_DAYS = 30;

async function download() {
  console.error('Downloading the Hetzner API description (about 3 MB, once)...');
  const response = await fetch(SPEC_URL, {
    headers: { 'User-Agent': 'itqan-agent-toolkit/1.0 (+https://github.com/itqanlab/agent-toolkit)' },
  });
  if (!response.ok) {
    throw new Error(
      `Could not download the API description (HTTP ${response.status}).\n` +
      'It needs network access. The wrapped commands in hz.mjs do not depend on this.',
    );
  }
  const body = await response.text();
  mkdirSync(dirname(SPEC_PATH), { recursive: true });
  writeFileSync(SPEC_PATH, body);
  console.error(`Saved to ${SPEC_PATH}\n`);
  return JSON.parse(body);
}

async function loadSpec({ refresh = false } = {}) {
  if (!refresh && existsSync(SPEC_PATH)) {
    const ageDays = (Date.now() - statSync(SPEC_PATH).mtimeMs) / 86_400_000;
    if (ageDays > STALE_AFTER_DAYS) {
      console.error(`(the cached description is ${Math.round(ageDays)} days old — "api.mjs refresh" updates it)\n`);
    }
    return JSON.parse(readFileSync(SPEC_PATH, 'utf8'));
  }
  return download();
}

const METHODS = ['get', 'post', 'put', 'patch', 'delete'];

/** Every operation as a flat list, so searching is a filter rather than a walk. */
function operations(spec) {
  const out = [];
  for (const [path, item] of Object.entries(spec.paths || {})) {
    for (const method of METHODS) {
      const op = item[method];
      if (op) out.push({ method: method.toUpperCase(), path, summary: op.summary || '', op });
    }
  }
  return out;
}

/** Follow a "#/components/..." pointer; an unresolved one tells the reader nothing. */
function deref(node, spec, seen = new Set()) {
  let current = node;
  while (current && current.$ref) {
    if (seen.has(current.$ref)) return { description: `(circular: ${current.$ref})` };
    seen.add(current.$ref);
    const parts = current.$ref.replace(/^#\//, '').split('/');
    current = parts.reduce((acc, part) => acc?.[decodeURIComponent(part.replace(/~1/g, '/').replace(/~0/g, '~'))], spec);
  }
  return current;
}

/** Show a schema as a short field list; raw JSON Schema is unreadable inline. */
function describeSchema(schema, spec, depth = 0, seen = new Set()) {
  const node = deref(schema, spec, new Set(seen));
  if (!node || depth > 2) return [];

  if (node.allOf) return node.allOf.flatMap((s) => describeSchema(s, spec, depth, seen));

  const variants = node.oneOf || node.anyOf;
  if (variants) {
    const pad = '  '.repeat(depth + 1);
    const labels = variants
      .map((v) => deref(v, spec, new Set(seen)))
      .map((v) => v?.properties?.type?.enum?.[0] || v?.title)
      .filter(Boolean);
    const head = variants.length === 1
      ? []
      : [`${pad}(${variants.length} shapes${labels.length ? `: ${labels.slice(0, 12).join(' | ')}` : ''})`];
    return [...head, ...describeSchema(variants[0], spec, depth, seen)];
  }

  const lines = [];
  const required = new Set(node.required || []);
  for (const [name, raw] of Object.entries(node.properties || {})) {
    const prop = deref(raw, spec, new Set(seen)) || {};
    const type = prop.type || (prop.oneOf || prop.anyOf ? 'one of' : prop.properties ? 'object' : '?');
    const enums = prop.enum ? ` = ${prop.enum.slice(0, 6).join(' | ')}${prop.enum.length > 6 ? ' | ...' : ''}` : '';
    const note = prop.description ? ` — ${String(prop.description).split('\n')[0].slice(0, 70)}` : '';
    lines.push(`${'  '.repeat(depth + 1)}${required.has(name) ? '*' : ' '} ${name} (${type})${enums}${note}`);
    if (prop.properties && depth < 2) lines.push(...describeSchema(prop, spec, depth + 1, seen));
  }
  return lines;
}

const COMMANDS = {
  async search(words) {
    const terms = words.filter((w) => !w.startsWith('--')).map((w) => w.toLowerCase());
    if (!terms.length) throw new Error('usage: api.mjs search <words...>   e.g. api.mjs search firewall rules');

    const spec = await loadSpec({ refresh: words.includes('--refresh') });
    const matches = operations(spec).filter(({ path, summary }) => {
      const haystack = `${path} ${summary}`.toLowerCase();
      return terms.every((t) => haystack.includes(t));
    });

    if (!matches.length) {
      console.log(`nothing matched "${terms.join(' ')}"`);
      console.log("Try fewer or more general words — the paths use Hetzner's own naming.");
      return;
    }
    console.log(`${matches.length} endpoint${matches.length === 1 ? '' : 's'} matched\n`);
    for (const m of matches.slice(0, 40)) {
      console.log(`${m.method.padEnd(7)} ${m.path}`);
      if (m.summary) console.log(`        ${m.summary}`);
    }
    if (matches.length > 40) console.log(`\n...and ${matches.length - 40} more. Add another word to narrow it.`);
    console.log(`\nDetail:  node scripts/api.mjs show "${matches[0].path}" ${matches[0].method.toLowerCase()}`);
  },

  async show([path, method = 'get']) {
    if (!path) throw new Error('usage: api.mjs show <path> [method]');
    const spec = await loadSpec();
    const item = spec.paths?.[path];
    if (!item) {
      console.log(`no such path: ${path}`);
      console.log('Paths are exact, including the {placeholders}. Find one with:  node scripts/api.mjs search <words>');
      process.exitCode = 1;
      return;
    }
    const op = item[method.toLowerCase()];
    if (!op) {
      console.log(`${path} has no ${method.toUpperCase()}. It supports: ${METHODS.filter((m) => item[m]).join(', ').toUpperCase()}`);
      process.exitCode = 1;
      return;
    }

    console.log(`${method.toUpperCase()} ${path}`);
    if (op.summary) console.log(`\n${op.summary}`);

    const params = (op.parameters || [])
      .map((p) => deref(p, spec) || {})
      .filter((p) => p.name && p.in !== 'header');
    if (params.length) {
      console.log('\nparameters');
      for (const p of params) {
        console.log(`  ${p.required ? '*' : ' '} ${p.name} (in ${p.in})${p.description ? ` — ${String(p.description).split('\n')[0].slice(0, 70)}` : ''}`);
      }
    }

    const schema = op.requestBody?.content?.['application/json']?.schema;
    if (schema) {
      console.log('\nrequest body   (* = required)');
      const lines = describeSchema(schema, spec);
      console.log(lines.length ? lines.join('\n') : '  (free-form)');
    }

    console.log(`\ncall it with:\n  import { request } from './scripts/hz.mjs';`);
    console.log(`  await request('${path}'${method.toLowerCase() === 'get' ? '' : `, { method: '${method.toUpperCase()}', body: { ... } }`});`);

    // Anything under /actions/ returns a job that is still running. Forgetting to
    // wait for it is the most common way code against this API appears to work
    // and then does not.
    if (/\/actions\//.test(path) && method.toLowerCase() === 'post') {
      console.log('\nThis returns an action that is still running. Wait for it:');
      console.log("  import { request, waitForAction } from './scripts/hz.mjs';");
      console.log(`  const { action } = await request('${path}', { method: 'POST', body: { ... } });`);
      console.log("  await waitForAction(action, { label: 'what this is doing' });");
    }
  },

  async refresh() {
    const spec = await download();
    console.log(`${Object.keys(spec.paths || {}).length} endpoints available offline`);
  },
};

const [command, ...args] = process.argv.slice(2);
const handler = COMMANDS[command];
if (!handler) {
  console.error(`usage: api.mjs <${Object.keys(COMMANDS).join('|')}> [args]`);
  process.exit(2);
}
try {
  await handler(args);
} catch (err) {
  console.error(`error: ${err.message}`);
  process.exit(1);
}
