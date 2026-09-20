#!/usr/bin/env node
// check.mjs — compare the toolkit skills installed on this machine with the latest releases.
//
// Read-only. It finds installed copies in the folders agents keep skills in, reads the
// version each one declares, reads the toolkit's update feed, and prints what changed in
// every newer version. It never installs, updates or deletes anything.
//
// Usage: node scripts/check.mjs [--json] [--available] [--feed URL|FILE] [--dir DIR ...]
//   --json        machine-readable output
//   --available   also list toolkit skills that are not installed
//   --feed        feed address or file (default: the public feed, or AGENT_TOOLKIT_FEED)
//   --dir         also look in this folder of skills (repeatable)
//
// Exit code: 0 all current, 10 an update is available, 2 the feed could not be read,
// 1 bad usage.

import { readFileSync, readdirSync, existsSync, realpathSync, statSync } from 'node:fs';
import { homedir } from 'node:os';
import { join, resolve, sep } from 'node:path';

const DEFAULT_FEED = 'https://agent-toolkit.itqanlab.com/updates.json';
const PUBLISHER = 'itqanlab';

/* ------------------------------------------------------------------ args */

const args = process.argv.slice(2);
const flag = (name) => args.includes(name);
const values = (name) => args.flatMap((a, i) => (a === name && args[i + 1] ? [args[i + 1]] : []));
if (flag('--help') || flag('-h')) {
  console.log(readFileSync(new URL(import.meta.url), 'utf8').split('\n').slice(1, 16)
    .map((l) => l.replace(/^\/\/ ?/, '')).join('\n'));
  process.exit(0);
}
for (const a of args) {
  if (a.startsWith('--') && !['--json', '--available', '--feed', '--dir'].includes(a)) {
    console.error(`unknown option: ${a}`);
    process.exit(1);
  }
}
const asJson = flag('--json');
const feedSource = values('--feed')[0] || process.env.AGENT_TOOLKIT_FEED || DEFAULT_FEED;

/* -------------------------------------------------------- version helpers */

const parse = (v) => String(v).split('.').map((n) => parseInt(n, 10) || 0);
function cmp(a, b) {
  const x = parse(a), y = parse(b);
  for (let i = 0; i < 3; i++) if (x[i] !== y[i]) return x[i] - y[i];
  return 0;
}

/* ------------------------------------------------------------ find copies */

const HOME = homedir();
const CODEX_HOME = process.env.CODEX_HOME || join(HOME, '.codex');
const cwd = process.cwd();

// Folders that hold skills, one skill per subfolder.
const skillRoots = [
  join(HOME, '.agents', 'skills'),
  join(HOME, '.claude', 'skills'),
  join(CODEX_HOME, 'skills'),
  join(HOME, '.cursor', 'skills'),
  join(HOME, '.gemini', 'skills'),
  join(HOME, '.copilot', 'skills'),
  join(HOME, '.config', 'opencode', 'skills'),
  join(HOME, '.config', 'agents', 'skills'),
  join(HOME, '.config', 'amp', 'skills'),
  join(HOME, '.config', 'goose', 'skills'),
  ...['.agents', '.claude', '.codex', '.cursor', '.gemini', '.opencode', '.goose', '.github']
    .map((d) => join(cwd, d, 'skills')),
  ...values('--dir').map((d) => resolve(d)),
];

const isDir = (p) => { try { return statSync(p).isDirectory(); } catch { return false; } };
const subdirs = (p) => (isDir(p) ? readdirSync(p).map((n) => join(p, n)).filter(isDir) : []);

// Claude Code and Codex both keep an installed plugin at <cache>/<marketplace>/<plugin>/<version>/.
// The skill sits in skills/<name>/ there. Older toolkit releases put SKILL.md at the top, so
// that shape is read too. Old versions can stay on disk, so only the newest one counts below.
const pluginCaches = [
  { agent: 'claude', dir: join(HOME, '.claude', 'plugins', 'cache') },
  { agent: 'codex', dir: join(CODEX_HOME, 'plugins', 'cache') },
];
const cacheInfo = new Map(); // skill folder -> { agent, market, plugin }
const cachedCopies = pluginCaches.flatMap(({ agent, dir }) => subdirs(dir).flatMap((market) =>
  subdirs(market).flatMap((plugin) => subdirs(plugin).flatMap((versionDir) => {
    const folders = existsSync(join(versionDir, 'SKILL.md')) ? [versionDir] : subdirs(join(versionDir, 'skills'));
    return folders.filter((f) => existsSync(join(f, 'SKILL.md'))).map((folder) => {
      cacheInfo.set(folder, { agent, market: market.split(sep).pop(), plugin: plugin.split(sep).pop(), root: dir });
      return folder;
    });
  }))));

const candidates = [
  ...skillRoots.flatMap(subdirs).filter((d) => existsSync(join(d, 'SKILL.md'))),
  ...cachedCopies,
];

// Only what the frontmatter says: name, and metadata.author / metadata.version.
function readHeader(dir) {
  const text = readFileSync(join(dir, 'SKILL.md'), 'utf8');
  if (!text.startsWith('---')) return null;
  const end = text.indexOf('\n---', 3);
  if (end === -1) return null;
  const head = {};
  let inMeta = false;
  for (const line of text.slice(4, end).split('\n')) {
    const top = line.match(/^([A-Za-z0-9_-]+):\s*(.*)$/);
    if (top) {
      inMeta = top[1] === 'metadata' && top[2] === '';
      if (!inMeta) head[top[1]] = top[2].replace(/^["']|["']$/g, '').trim();
      continue;
    }
    const nested = inMeta && line.match(/^\s+([A-Za-z0-9_-]+):\s*(.*)$/);
    if (nested) head[`metadata.${nested[1]}`] = nested[2].replace(/^["']|["']$/g, '').trim();
  }
  return head;
}

/* ---------------------------------------------------------------- feed */

async function loadFeed(source) {
  let raw;
  if (/^https?:\/\//i.test(source)) {
    const res = await fetch(source, { signal: AbortSignal.timeout(15000), headers: { accept: 'application/json' } });
    if (!res.ok) throw new Error(`${source} answered ${res.status}`);
    raw = await res.text();
  } else {
    raw = readFileSync(source, 'utf8');
  }
  const feed = JSON.parse(raw);
  if (feed.schema !== 1 || !Array.isArray(feed.items)) throw new Error('not an update feed this script understands (expected schema 1)');
  return feed;
}

let feed;
try {
  feed = await loadFeed(feedSource);
} catch (e) {
  const reason = e && e.cause && e.cause.code ? `${e.message} (${e.cause.code})` : e.message;
  if (asJson) console.log(JSON.stringify({ error: `could not read the update feed: ${reason}`, feed: feedSource }, null, 2));
  else {
    console.error(`Could not read the update feed: ${reason}`);
    console.error(`  feed: ${feedSource}`);
    if (/^https?:/i.test(feedSource)) console.error('If the network is blocked, for example by a sandbox, allow it and run this again.');
    console.error('Each installed skill has a CHANGELOG.md. Its "Latest:" line is an address you can open');
    console.error('to see the newest version by hand.');
  }
  process.exit(2);
}
const byName = new Map(feed.items.map((i) => [i.name, i]));

/* ------------------------------------------------------ what is installed */

// One entry per real folder. A symlinked install and its target are the same copy.
const copies = new Map();
for (const dir of candidates) {
  const head = readHeader(dir);
  if (!head || !byName.has(head.name)) continue;
  if (head['metadata.author'] !== PUBLISHER) continue; // same name, different publisher
  let real = dir;
  try { real = realpathSync(dir); } catch { /* keep dir */ }
  const entry = copies.get(real) || { name: head.name, version: head['metadata.version'] || '0.0.0', real, at: [] };
  entry.at.push(dir);
  copies.set(real, entry);
}

// A plugin cache can hold several versions of the same plugin. Only the newest one is the
// installed copy, so an older folder left on disk is not reported as behind.
const newestCached = new Map();
for (const [real, entry] of copies) {
  const info = cacheInfo.get(entry.at[0]);
  if (!info) continue;
  const key = `${info.agent}:${info.market}:${info.plugin}`;
  const best = newestCached.get(key);
  if (!best || cmp(entry.version, best.entry.version) > 0) newestCached.set(key, { real, entry });
}
for (const [real, entry] of [...copies]) {
  const info = cacheInfo.get(entry.at[0]);
  if (!info) continue;
  if (newestCached.get(`${info.agent}:${info.market}:${info.plugin}`).real !== real) copies.delete(real);
}

// The feed names the repository. Older feeds did not, so fall back to the changelog address.
const repoOf = (item) => {
  if (feed.repository) return feed.repository;
  const m = String(item.changelog || '').match(/raw\.githubusercontent\.com\/([^/]+\/[^/]+)\//);
  return m ? `https://github.com/${m[1]}` : null;
};

function locationKind(entry) {
  const p = entry.at[0];
  const info = cacheInfo.get(p);
  if (info) return `${info.agent}-plugin`;
  if (entry.real !== p) return 'link';
  if (p.startsWith(cwd + sep)) return 'project';
  if (p.startsWith(join(HOME, '.claude') + sep)) return 'claude-skills';
  return 'user';
}

const KIND_LABEL = {
  'claude-plugin': 'Claude Code plugin',
  'codex-plugin': 'Codex plugin',
  link: 'linked to a clone',
  project: 'this project',
  'claude-skills': 'Claude Code skills folder',
  user: 'skills folder',
};

function howToUpdate(entry, item) {
  const repo = repoOf(item) || 'the source repository';
  const kind = locationKind(entry);
  const clone = `In a clone of ${repo} (git clone it if you have none): git pull`;
  switch (kind) {
    case 'claude-plugin': {
      const { market } = cacheInfo.get(entry.at[0]);
      return `/plugin marketplace update ${market}, then /plugin install ${item.name}@${market}`;
    }
    case 'codex-plugin': {
      const { market } = cacheInfo.get(entry.at[0]);
      return `codex plugin marketplace upgrade ${market}, then codex plugin add ${item.name}@${market}. Start a new session afterwards.`;
    }
    case 'link': return `${clone}. This copy is a link to ${entry.real}, so pulling is enough.`;
    case 'project': return `${clone}, then from this project run: <clone>/scripts/install.sh --project --force ${item.name}`;
    case 'claude-skills': return `${clone}, then: ./scripts/install.sh --claude --force ${item.name}`;
    default: return `${clone}, then: ./scripts/install.sh --force ${item.name}`;
  }
}

const results = [...copies.values()]
  .sort((a, b) => a.name.localeCompare(b.name))
  .map((entry) => {
    const item = byName.get(entry.name);
    const diff = cmp(item.version, entry.version);
    const status = diff > 0 ? 'update' : diff < 0 ? 'ahead' : 'current';
    const releases = status === 'update'
      ? item.releases.filter((r) => cmp(r.version, entry.version) > 0).sort((a, b) => cmp(a.version, b.version))
      : [];
    return {
      name: entry.name,
      installed: entry.version,
      latest: item.version,
      status,
      breaking: releases.some((r) => r.breaking),
      locations: entry.at,
      kind: locationKind(entry),
      howToUpdate: status === 'update' ? howToUpdate(entry, item) : null,
      releases,
    };
  });

const installedNames = new Set(results.map((r) => r.name));
const available = feed.items.filter((i) => !installedNames.has(i.name)).map((i) => i.name);
const pending = results.filter((r) => r.status === 'update');

/* --------------------------------------------------------------- output */

const tilde = (p) => (p.startsWith(HOME + sep) ? `~${p.slice(HOME.length)}` : p);

if (asJson) {
  console.log(JSON.stringify({
    feed: { address: feedSource, updated: feed.updated },
    installed: results.map((r) => ({ ...r, locations: r.locations })),
    available: flag('--available') ? available : undefined,
  }, null, 2));
  process.exit(pending.length ? 10 : 0);
}

console.log(`Toolkit updates (feed updated ${feed.updated})`);
console.log('');
if (!results.length) {
  console.log('No toolkit skills found in the usual folders.');
  console.log('If they live somewhere else, run this again with --dir <folder>.');
}
for (const r of results) {
  const where = `[${KIND_LABEL[r.kind] || r.kind}]`;
  if (r.status === 'current') { console.log(`${r.name}  ${r.installed}  up to date  ${where}`); continue; }
  if (r.status === 'ahead') { console.log(`${r.name}  ${r.installed}  newer than the feed (${r.latest}). A development copy, most likely.  ${where}`); continue; }
  console.log(`${r.name}  ${r.installed} -> ${r.latest}  UPDATE AVAILABLE${r.breaking ? '  (breaking change, you must act)' : ''}  ${where}`);
  for (const l of r.locations) console.log(`  installed at ${tilde(l)}`);
  console.log('  What changed:');
  for (const rel of r.releases) {
    console.log(`    ${rel.version}  ${rel.date}${rel.breaking ? '  BREAKING' : ''}`);
    const order = ['Breaking', 'Added', 'Changed', 'Deprecated', 'Removed', 'Fixed', 'Security'];
    for (const sec of order.filter((s) => rel.changes[s])) {
      for (const line of rel.changes[sec]) console.log(`      ${sec}: ${line}`);
    }
  }
  console.log(`  To update: ${r.howToUpdate}`);
  console.log('');
}

const skillCount = new Set(results.map((r) => r.name)).size;
const tail = results.length
  ? `${results.length} ${results.length === 1 ? 'copy' : 'copies'} found (${skillCount} ${skillCount === 1 ? 'skill' : 'skills'}), ${pending.length} can be updated.`
  : '';
if (tail) console.log(tail);
if (flag('--available') && available.length) {
  console.log(`Not installed: ${available.join(', ')}`);
}
process.exit(pending.length ? 10 : 0);
