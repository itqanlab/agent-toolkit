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
//   .agents/plugins/marketplace.json  the catalog Codex reads
//   plugins/<name>/.codex-plugin/plugin.json   the manifest Codex reads, one per plugin
//   .agents/skills/<name>/            a copy of each skill folder, for Amp (see below)
//
// It also fails, in both modes, on a skill that is missing a piece the catalog needs,
// including a CHANGELOG.md whose newest entry is not the skill's current version.

import { readFileSync, writeFileSync, existsSync, readdirSync, mkdirSync, rmSync, statSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { readPlugins, readSkills, deps, splitDescription, SITE_URL } from './lib/catalog.mjs';
import { parseChangelog } from './lib/changelog.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const MARKETPLACE = join(ROOT, '.claude-plugin', 'marketplace.json');
const README = join(ROOT, 'README.md');
const CODEX = join(ROOT, '.agents', 'plugins', 'marketplace.json');
const START = '<!-- skills:start -->';
const END = '<!-- skills:end -->';
const check = process.argv.includes('--check');

// CRLF is read as LF, so a Windows working tree does not look out of date.
const read = (p) => readFileSync(p, 'utf8').replace(/\r\n?/g, '\n');
const existing = JSON.parse(read(MARKETPLACE));
const categories = JSON.parse(read(join(ROOT, 'catalog', 'categories.json'))).categories;
const categoryIds = categories.map((c) => c.id);
const repoUrl = existing.owner.url;

const errors = [];
const fail = (skill, msg) => errors.push(`${skill}: ${msg}`);

// Each plugin must hold exactly one skill, named like the plugin. Bundles come later.
for (const pl of readPlugins(ROOT)) {
  if (!pl.manifest) fail(pl.name, 'no .claude-plugin/plugin.json');
  else if (pl.skills.length !== 1) fail(pl.name, `a plugin holds one skill for now, found ${pl.skills.length} in skills/`);
  else if (pl.skills[0].name !== pl.name) fail(pl.name, `the skill inside is "${pl.skills[0].name}". It must be named like the plugin`);
}

// A trigger phrase is a fine starter prompt when it is a real phrase, not a command.
const isPrompt = (t) => t.length >= 12 && t.includes(' ') && !t.startsWith('/');

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
  // Codex shows a short line and starter prompts. The short line is written by hand.
  // Codex asks for 25 to 64 characters, so the line scans well in its skill list.
  if (!meta.short) fail(s.name, 'SKILL.md metadata has no short description (25 to 64 characters, for the Codex plugin card and skill list)');
  else if (meta.short.length < 25 || meta.short.length > 64) fail(s.name, `metadata.short is ${meta.short.length} characters. Codex asks for 25 to 64`);
  if (!meta.starter) fail(s.name, 'SKILL.md metadata has no starter (what to ask, for example "tell me why the last deploy failed"; up to 100 characters)');
  else if (meta.starter.length > 100) fail(s.name, `metadata.starter is ${meta.starter.length} characters, the limit is 100`);
  if (meta.access !== undefined && meta.access !== 'read') fail(s.name, 'metadata.access can only be "read". Leave it out for a skill that changes things');
  if (!p.author || !p.author.name) fail(s.name, 'plugin.json has no author.name');
  if (splitDescription(s.fm.description).triggers.filter(isPrompt).length === 0) {
    fail(s.name, 'the description needs at least one trigger phrase of 12 or more characters, for the Codex starter prompts');
  }
  if (meta.featured !== undefined && !['true', 'false'].includes(meta.featured)) {
    fail(s.name, `metadata.featured must be "true" or "false", not "${meta.featured}"`);
  }
  const home = `${repoUrl}/tree/main/plugins/${s.name}`;
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
    // The site address, not a path in the repository, so it survives another re-layout.
    const latest = `${SITE_URL}/s/${s.name}/CHANGELOG.md`;
    if (changelog.latestUrl && changelog.latestUrl !== latest) fail(s.name, `CHANGELOG.md "Latest:" should be ${latest}`);
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
  source: `./plugins/${name}`,
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
  return `| [\`${name}\`](plugins/${name}/skills/${name}) | ${meta.category} | [${p.version}](plugins/${name}/skills/${name}/CHANGELOG.md) | ${firstSentence(p.description)} | ${needs} |`;
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

/* ----------------------------------------------------------- codex plugins */

// Codex has its own manifest, .codex-plugin/plugin.json, and its own catalog,
// .agents/plugins/marketplace.json, which it reads before the Claude one. Both are written
// from what is already said about the skill, so nothing is said twice. A Codex plugin must
// hold its skills in a skills/ folder. That is why each plugin lives in plugins/<name>/.
const titleCase = (n) => n.split('-').map((w) => w[0].toUpperCase() + w.slice(1)).join(' ');
const sentenceCase = (t) => t[0].toUpperCase() + t.slice(1);
const codexCategory = (id) => (categories.find((c) => c.id === id) || {}).codex || 'Other';

const codexManifests = skills.map(({ name, p, meta, fm, pluginRoot }) => {
  const manifest = {
    name,
    version: p.version,
    description: p.description,
    author: p.author,
    homepage: p.homepage,
    repository: p.repository,
    license: p.license,
    keywords: p.keywords,
    skills: './skills/',
    interface: {
      displayName: p.displayName || titleCase(name),
      shortDescription: meta.short,
      longDescription: p.description,
      developerName: p.author.name,
      category: codexCategory(meta.category),
      capabilities: meta.access === 'read' ? ['Interactive', 'Read'] : ['Interactive', 'Read', 'Write'],
      websiteURL: `${SITE_URL}/s/${name}/`,
      defaultPrompt: splitDescription(fm.description).triggers.filter(isPrompt).slice(0, 3)
        .map((t) => sentenceCase(t).slice(0, 128)),
    },
  };
  return [join(pluginRoot, '.codex-plugin', 'plugin.json'), `${JSON.stringify(manifest, null, 2)}\n`,
    `plugins/${name}/.codex-plugin/plugin.json`];
});

// agents/openai.yaml is what Codex reads for the skill list: a display name, a short line and a
// starter prompt. It sits inside the skill folder, so it travels with every install. Other agents
// ignore it. The values are JSON strings, which are valid YAML, so quoting is never wrong.
const openaiYaml = skills.map(({ name, p, meta, base }) => [
  join(base, 'agents', 'openai.yaml'),
  [
    'interface:',
    `  display_name: ${JSON.stringify(p.displayName || titleCase(name))}`,
    `  short_description: ${JSON.stringify(meta.short)}`,
    `  default_prompt: ${JSON.stringify(`Use $${name} to ${meta.starter}.`)}`,
    '',
  ].join('\n'),
  `plugins/${name}/skills/${name}/agents/openai.yaml`,
]);

const codex = `${JSON.stringify({
  name: existing.name,
  interface: { displayName: 'Itqan Agent Toolkit' },
  plugins: skills.map(({ name, meta }) => ({
    name,
    source: { source: 'local', path: `./plugins/${name}` },
    policy: { installation: 'AVAILABLE', authentication: 'ON_INSTALL' },
    category: codexCategory(meta.category),
  })),
}, null, 2)}\n`;

/* ------------------------------------------------------- .agents/skills copy */

// Amp reads a repository's skills from skills/, .agents/skills/, .claude/skills/, the root and
// one folder below it. It does not look in plugins/<name>/skills/<name>, so without this copy
// `amp skills add itqanlab/agent-toolkit` finds nothing. It also skips symbolic links, so a link
// would not help. Only a real copy works, and this is it. Edit the skill under plugins/, never
// this copy. Codex, Claude Code, Gemini and Copilot read plugins/ or an explicit path, and
// `npx skills` reads this folder and plugins/ and lists each skill once.
const MIRROR = join(ROOT, '.agents', 'skills');
const overlay = new Map(openaiYaml.map(([path, text]) => [path, text]));
const listFiles = (dir) => readdirSync(dir, { recursive: true, withFileTypes: true })
  .filter((e) => e.isFile()).map((e) => join(e.parentPath, e.name));

const mirrorFiles = skills.flatMap(({ name, base }) => listFiles(base).map((file) => {
  const rel = file.slice(base.length + 1).split('\\').join('/');
  // A file this script writes is copied from what it will write, so a stale one on disk cannot leak in.
  const text = overlay.get(file);
  const body = text === undefined ? readFileSync(file) : Buffer.from(text);
  return { path: join(MIRROR, name, ...rel.split('/')), body, from: file, label: `.agents/skills/${name}/${rel}` };
}));
const mirrorPaths = new Set(mirrorFiles.map((f) => f.path));
const sameBytes = (path, body) => {
  if (!existsSync(path)) return false;
  const now = readFileSync(path);
  // Text is compared as LF, like every other generated file, so a CRLF checkout is not "stale".
  return now.equals(body) || (!body.includes(0) && read(path) === body.toString('utf8').replace(/\r\n?/g, '\n'));
};
const leftovers = existsSync(MIRROR)
  ? listFiles(MIRROR).filter((f) => !mirrorPaths.has(f))
  : [];

/* ------------------------------------------------------------------ write */

const targets = [
  [MARKETPLACE, marketplace, '.claude-plugin/marketplace.json'],
  [README, nextReadme, 'README.md'],
  [CODEX, codex, '.agents/plugins/marketplace.json'],
  ...codexManifests,
  ...openaiYaml,
];

if (check) {
  const stale = targets.filter(([path, next]) => !existsSync(path) || read(path) !== next).map(([, , label]) => label);
  for (const f of mirrorFiles) if (!sameBytes(f.path, f.body)) stale.push(f.label);
  for (const f of leftovers) stale.push(`${f.slice(ROOT.length + 1).split('\\').join('/')} (not in any skill)`);
  if (stale.length) {
    console.error('catalog: out of date. Run: node scripts/build-catalog.mjs');
    for (const label of stale) console.error(`  ✘ ${label}`);
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
  let copied = 0;
  for (const f of mirrorFiles) {
    if (sameBytes(f.path, f.body)) continue;
    mkdirSync(dirname(f.path), { recursive: true });
    writeFileSync(f.path, f.body, { mode: statSync(f.from).mode });
    copied++;
  }
  for (const f of leftovers) rmSync(f);
  if (existsSync(MIRROR)) {
    // Drop folders a removed skill or file left empty, deepest first.
    const dirs = readdirSync(MIRROR, { recursive: true, withFileTypes: true }).filter((e) => e.isDirectory())
      .map((e) => join(e.parentPath, e.name)).sort((a, b) => b.length - a.length);
    for (const d of dirs) if (readdirSync(d).length === 0) rmSync(d, { recursive: true });
  }
  if (copied || leftovers.length) console.log(`wrote .agents/skills (${copied} files copied, ${leftovers.length} removed)`);
  console.log(`catalog: ${skills.length} skills`);
}
