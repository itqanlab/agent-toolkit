#!/usr/bin/env node
// api.mjs — search a Dokploy instance's own API description.
//
// The wrapped commands in dk.mjs cover the everyday work. Dokploy has around 540
// calls, though, and the rest are reachable with the same key — so the question
// for anything else is which call, and what it wants.
//
// Unlike a hosted service, the description is not published anywhere: each
// installation serves its own, and it matches the version actually running.
// That is better than a document on a website, which may describe a version this
// server has not been upgraded to. It does mean the fetch needs the key, and
// that the cache belongs to one instance rather than to the provider.
//
//   api.mjs search <words...>            find calls
//   api.mjs show <path> [method]         parameters and request body for one call
//   api.mjs refresh                      re-download from the instance

import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { storeRoot } from '../lib/store.mjs';
import { slug, takeTargetFlag } from '../lib/targets.mjs';
import { SPEC, request, useInstance, instance } from './dk.mjs';

const STALE_AFTER_DAYS = 30;
const specPath = () => join(storeRoot(), 'cache', `dokploy-${slug(instance().name).toLowerCase()}-openapi.json`);

async function download() {
  console.error(`Downloading the API description from ${instance().fields.url} (once)...`);
  const spec = await request('settings.getOpenApiDocument');
  if (!spec?.paths) {
    throw new Error(
      'That instance did not return an API description.\n' +
      'Older Dokploy versions do not serve one. The wrapped commands in dk.mjs do not depend on it.',
    );
  }
  const path = specPath();
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify(spec));
  console.error(`Saved to ${path}\n`);
  return spec;
}

async function loadSpec({ refresh = false } = {}) {
  const path = specPath();
  if (!refresh && existsSync(path)) {
    const ageDays = (Date.now() - statSync(path).mtimeMs) / 86_400_000;
    if (ageDays > STALE_AFTER_DAYS) {
      console.error(`(this description is ${Math.round(ageDays)} days old — "api.mjs refresh" re-reads it from the instance)\n`);
    }
    return JSON.parse(readFileSync(path, 'utf8'));
  }
  return download();
}

const METHODS = ['get', 'post', 'put', 'patch', 'delete'];

function operations(spec) {
  const out = [];
  for (const [path, item] of Object.entries(spec.paths || {})) {
    for (const method of METHODS) {
      const op = item[method];
      if (op) out.push({ method: method.toUpperCase(), path, summary: op.summary || op.operationId || '', op });
    }
  }
  return out;
}

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

function describeSchema(schema, spec, depth = 0, seen = new Set()) {
  const node = deref(schema, spec, new Set(seen));
  if (!node || depth > 2) return [];
  if (node.allOf) return node.allOf.flatMap((s) => describeSchema(s, spec, depth, seen));

  const variants = node.oneOf || node.anyOf;
  if (variants) return describeSchema(variants[0], spec, depth, seen);

  const lines = [];
  const required = new Set(node.required || []);
  for (const [name, raw] of Object.entries(node.properties || {})) {
    const prop = deref(raw, spec, new Set(seen)) || {};
    const type = prop.type || (prop.properties ? 'object' : '?');
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
    if (!terms.length) throw new Error('usage: api.mjs search <words...>   e.g. api.mjs search backup postgres');

    const spec = await loadSpec({ refresh: words.includes('--refresh') });
    const matches = operations(spec).filter(({ path, summary }) => {
      const haystack = `${path} ${summary}`.toLowerCase();
      return terms.every((t) => haystack.includes(t));
    });

    if (!matches.length) {
      console.log(`nothing matched "${terms.join(' ')}"`);
      console.log('Calls are named router.procedure — try the name of the thing, such as "postgres" or "domain".');
      return;
    }
    console.log(`${matches.length} call${matches.length === 1 ? '' : 's'} matched on "${instance().name}"\n`);
    for (const m of matches.slice(0, 40)) {
      console.log(`${m.method.padEnd(7)} ${m.path}`);
      if (m.summary && m.summary !== m.path.replace(/^\//, '').replace('.', '-')) console.log(`        ${m.summary}`);
    }
    if (matches.length > 40) console.log(`\n...and ${matches.length - 40} more. Add another word to narrow it.`);
    console.log(`\nDetail:  node scripts/api.mjs show "${matches[0].path}" ${matches[0].method.toLowerCase()}`);
  },

  async show([path, method]) {
    if (!path) throw new Error('usage: api.mjs show <path> [method]');
    const spec = await loadSpec();
    const key = path.startsWith('/') ? path : `/${path}`;
    const item = spec.paths?.[key];
    if (!item) {
      console.log(`no such call: ${key}`);
      console.log('Find one with:  node scripts/api.mjs search <words>');
      process.exitCode = 1;
      return;
    }
    const verb = (method || METHODS.find((m) => item[m]) || 'get').toLowerCase();
    const op = item[verb];
    if (!op) {
      console.log(`${key} has no ${verb.toUpperCase()}. It supports: ${METHODS.filter((m) => item[m]).join(', ').toUpperCase()}`);
      process.exitCode = 1;
      return;
    }

    console.log(`${verb.toUpperCase()} ${key}`);
    if (op.summary) console.log(`\n${op.summary}`);

    const params = (op.parameters || []).map((p) => deref(p, spec) || {}).filter((p) => p.name && p.in !== 'header');
    if (params.length) {
      console.log('\nparameters   (* = required, sent in the query string)');
      for (const p of params) console.log(`  ${p.required ? '*' : ' '} ${p.name}${p.description ? ` — ${String(p.description).split('\n')[0].slice(0, 70)}` : ''}`);
    }

    const schema = op.requestBody?.content?.['application/json']?.schema;
    if (schema) {
      console.log('\nrequest body   (* = required)');
      const lines = describeSchema(schema, spec);
      console.log(lines.length ? lines.join('\n') : '  (free-form)');
    }

    console.log(`\ncall it with:\n  import { request, findService } from './scripts/dk.mjs';`);
    console.log(verb === 'get'
      ? `  await request('${key.slice(1)}', { query: { /* from above */ } });`
      : `  await request('${key.slice(1)}', { method: '${verb.toUpperCase()}', body: { /* from above */ } });`);
    console.log('\nIds are not visible in the dashboard. findService(name) turns a name into one.');
  },

  async refresh() {
    const spec = await download();
    console.log(`${Object.keys(spec.paths || {}).length} calls available offline for "${instance().name}"`);
  },
};

const { name: instanceName, args: argv } = takeTargetFlag(process.argv.slice(2), SPEC);
const [command, ...args] = argv;
const handler = COMMANDS[command];
if (!handler) {
  console.error(`usage: api.mjs [--instance <name>] <${Object.keys(COMMANDS).join('|')}> [args]`);
  process.exit(2);
}
try {
  useInstance(instanceName);
  await handler(args);
} catch (err) {
  console.error(`error: ${err.message}`);
  process.exit(1);
}
