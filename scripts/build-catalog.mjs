#!/usr/bin/env node
// build-catalog.mjs — write the two files that list every skill, from the skill folders.
//
//   .claude-plugin/marketplace.json   the plugin entries
//   README.md                         the table between the skills:start/end markers
//
// A skill is described once: SKILL.md (name, description, metadata.category,
// metadata.version) and .claude-plugin/plugin.json (version, author, keywords...).
// Nothing is copied by hand into the catalog, so it cannot drift.
//
//   node scripts/build-catalog.mjs           write both files
//   node scripts/build-catalog.mjs --check   fail if either file is out of date
//
//   .agents/plugins/marketplace.json  the catalog Codex reads (see docs/COMPATIBILITY.md)
//
// It also fails, in both modes, on a skill that is missing a piece the catalog needs,
// including a CHANGELOG.md whose newest entry is not the skill's current version.

import { readFileSync, writeFileSync, existsSync, readdirSync, mkdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { readSkills, deps } from './lib/catalog.mjs';
import { parseChangelog } from './lib/changelog.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const MARKETPLACE = join(ROOT, '.claude-plugin', 'marketplace.json');
const README = join(ROOT, 'README.md');
const CODEX = join(ROOT, '.agents', 'plugins', 'marketplace.json');
const START = '<!-- skills:start -->';
const END = '<!-- skills:end -->';
const check = process.argv.includes('--check');

const read = (p) => readFileSync(p, 'utf8');
const existing = JSON.parse(read(MARKETPLACE));
const categories = JSON.parse(read(join(ROOT, 'catalog', 'categories.json'))).categories;
const categoryIds = categories.map((c) => c.id);
const repoUrl = existing.owner.url;

const errors = [];
const fail = (skill, msg) => errors.push(`${skill}: ${msg}`);

const skills = readSkills(ROOT).map((s) => {
  const meta = s.fm.metadata || {};
  const p = s.plugin;
  if (!p) { fail(s.name, 'no .claude-plugin/plugin.json'); return null; }
  if (p.name !== s.name) fail(s.name, `plugin.json name is "${p.name}"`);
  if (!p.version) fail(s.name, 'plugin.json has no version');
  if (p.version !== meta.version) {
    fail(s.name, `plugin.json version "${p.version}" differs from SKILL.md metadata.version "${meta.version}"`);
  }
  if (!p.description) fail(s.name, 'plugin.json has no description');
  if (!meta.category) fail(s.name, `SKILL.md metadata has no category (one of: ${categoryIds.join(', ')})`);
  else if (!categoryIds.includes(meta.category)) {
    fail(s.name, `category "${meta.category}" is not in catalog/categories.json (${categoryIds.join(', ')})`);
  }
  if (meta.featured !== undefined && !['true', 'false'].includes(meta.featured)) {
    fail(s.name, `metadata.featured must be "true" or "false", not "${meta.featured}"`);
  }
  const home = `${repoUrl}/tree/main/skills/${s.name}`;
  if (p.homepage !== home) fail(s.name, `plugin.json homepage should be ${home}`);

  // The changelog is how an agent learns what changed, so it is checked hard.
  const clPath = join(s.base, 'CHANGELOG.md');
  let changelog = null;
  if (!existsSync(clPath)) fail(s.name, 'no CHANGELOG.md');
  else {
    changelog = parseChangelog(read(clPath));
    for (const e of changelog.errors) fail(s.name, `CHANGELOG.md: ${e}`);
    const top = changelog.releases[0];
    if (top && top.version !== p.version) {
      fail(s.name, `CHANGELOG.md newest entry is ${top.version} but the version is ${p.version}. Add an entry for ${p.version}.`);
    }
    const raw = `${repoUrl.replace('https://github.com/', 'https://raw.githubusercontent.com/')}/main/skills/${s.name}/CHANGELOG.md`;
    if (changelog.latestUrl && changelog.latestUrl !== raw) fail(s.name, `CHANGELOG.md "Latest:" should be ${raw}`);
  }
  if (!read(join(s.base, 'SKILL.md')).includes('CHANGELOG.md')) {
    fail(s.name, 'SKILL.md does not point the agent at CHANGELOG.md (add the "Updates" section)');
  }
  return { ...s, meta, p, changelog };
}).filter(Boolean);

if (errors.length) {
  console.error('catalog: cannot build');
  for (const e of errors) console.error(`  ✘ ${e}`);
  process.exit(1);
}

// Group by category in the order the list declares, then by name.
skills.sort((a, b) =>
  categoryIds.indexOf(a.meta.category) - categoryIds.indexOf(b.meta.category) ||
  a.name.localeCompare(b.name));

/* ------------------------------------------------------------ marketplace */

const entries = skills.map(({ name, p, meta }) => ({
  name,
  source: `./skills/${name}`,
  description: p.description,
  version: p.version,
  author: p.author,
  homepage: p.homepage,
  repository: p.repository,
  license: p.license,
  category: meta.category,
  displayName: p.displayName,
  keywords: p.keywords,
}));

const marketplace = `${JSON.stringify({ ...existing, plugins: entries }, null, 2)}\n`;

/* ------------------------------------------------------------ readme table */

const firstSentence = (s) => s.split(/(?<=[.!?])\s/)[0];
const rows = skills.map(({ name, p, meta, fm }) => {
  const needs = deps(fm.compatibility).map((d) => `\`${d}\``).join(', ') || 'nothing';
  return `| [\`${name}\`](skills/${name}) | ${meta.category} | [${p.version}](skills/${name}/CHANGELOG.md) | ${firstSentence(p.description)} | ${needs} |`;
});
const table = [START, '| Skill | Category | Version | Does | Needs |', '| :-- | :-- | :-- | :-- | :-- |', ...rows, END].join('\n');

const readme = read(README);
const from = readme.indexOf(START);
const to = readme.indexOf(END);
if (from === -1 || to === -1 || to < from) {
  console.error(`catalog: README.md needs the markers ${START} and ${END} around the skills table`);
  process.exit(1);
}
const nextReadme = readme.slice(0, from) + table + readme.slice(to + END.length);

/* ------------------------------------------------------------ codex catalog */

// Codex reads .agents/plugins/marketplace.json before it reads the Claude file. A Codex
// plugin needs .codex-plugin/plugin.json and its skills under skills/<name>/, which a
// plain skill folder does not have. So without this file, Codex would list our skills as
// "installed" while showing the model nothing. Bundles that do carry a Codex manifest are
// listed here. Plain skills reach Codex through install.sh (docs/COMPATIBILITY.md).
const codexPlugins = [];
const bundles = join(ROOT, 'plugins');
if (existsSync(bundles)) {
  for (const e of readdirSync(bundles, { withFileTypes: true })) {
    if (e.isDirectory() && existsSync(join(bundles, e.name, '.codex-plugin', 'plugin.json'))) {
      codexPlugins.push({
        name: e.name,
        source: { source: 'local', path: `./plugins/${e.name}` },
        policy: { installation: 'AVAILABLE', authentication: 'ON_INSTALL' },
      });
    }
  }
}
const codex = `${JSON.stringify({
  name: existing.name,
  interface: { displayName: 'Itqan Agent Toolkit' },
  plugins: codexPlugins,
}, null, 2)}\n`;

/* ------------------------------------------------------------------ write */

const targets = [
  [MARKETPLACE, marketplace, '.claude-plugin/marketplace.json'],
  [README, nextReadme, 'README.md'],
  [CODEX, codex, '.agents/plugins/marketplace.json'],
];

if (check) {
  const stale = targets.filter(([path, next]) => !existsSync(path) || read(path) !== next);
  if (stale.length) {
    console.error('catalog: out of date. Run: node scripts/build-catalog.mjs');
    for (const [, , label] of stale) console.error(`  ✘ ${label}`);
    process.exit(1);
  }
  console.log(`catalog: up to date (${skills.length} skills)`);
} else {
  for (const [path, next, label] of targets) {
    if (!existsSync(path) || read(path) !== next) {
      mkdirSync(dirname(path), { recursive: true });
      writeFileSync(path, next);
      console.log(`wrote ${label}`);
    }
  }
  console.log(`catalog: ${skills.length} skills`);
}
