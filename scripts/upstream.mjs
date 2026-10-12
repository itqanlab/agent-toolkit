#!/usr/bin/env node
// upstream.mjs — what changed in the vendor skills our plugins are built on.
//
// A plugin that adapts someone else's material records it in plugins/<name>/upstream.json:
// the repo, the commit we last synced from, and which upstream folder feeds which of our
// files. This script compares that commit with the vendor's current one and lists the
// upstream folders that changed, so a sync starts from facts instead of a full re-read.
//
// Usage: node scripts/upstream.mjs [plugin...]
// Read-only. Uses the public GitHub API without a token (60 requests an hour), or
// GITHUB_TOKEN when it is set.

import { readFileSync, existsSync, readdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const wanted = process.argv.slice(2);

async function gh(path) {
  const headers = { Accept: 'application/vnd.github+json', 'User-Agent': 'itqan-agent-toolkit-upstream' };
  if (process.env.GITHUB_TOKEN) headers.Authorization = `Bearer ${process.env.GITHUB_TOKEN}`;
  const res = await fetch(`https://api.github.com${path}`, { headers });
  if (!res.ok) throw new Error(`GitHub answered ${res.status} for ${path}`);
  return res.json();
}

const slug = (repo) => repo.replace(/^https:\/\/github\.com\//, '').replace(/\.git$/, '');

let behind = 0;
for (const name of readdirSync(join(ROOT, 'plugins')).sort()) {
  const file = join(ROOT, 'plugins', name, 'upstream.json');
  if (!existsSync(file) || (wanted.length && !wanted.includes(name))) continue;
  for (const src of JSON.parse(readFileSync(file, 'utf8')).sources || []) {
    const repo = slug(src.repo);
    let cmp;
    let head;
    try {
      head = (await gh(`/repos/${repo}/commits?per_page=1`))[0].sha;
      if (head === src.commit) {
        console.log(`${name}  ${repo}  up to date (${src.commit.slice(0, 7)}, synced ${src.synced})`);
        continue;
      }
      cmp = await gh(`/repos/${repo}/compare/${src.commit}...${head}`);
    } catch (err) {
      console.log(`${name}  ${repo}  could not check: ${err.message}`);
      process.exitCode = 2;
      continue;
    }
    behind += 1;
    console.log(`${name}  ${repo}  ${cmp.ahead_by} new commit(s) since ${src.commit.slice(0, 7)} (synced ${src.synced})`);
    for (const c of cmp.commits.slice(-10)) {
      console.log(`    ${c.sha.slice(0, 7)} ${c.commit.author.date.slice(0, 10)} ${c.commit.message.split('\n')[0]}`);
    }
    // Group changed files by their top folder, the unit `map` and `not_adopted` speak in.
    const folders = {};
    for (const f of cmp.files || []) (folders[f.filename.split('/')[0]] ??= []).push(f.filename);
    for (const [folder, files] of Object.entries(folders)) {
      const ours = src.map?.[folder];
      const why = src.not_adopted?.[folder];
      const where = ours ? `-> ours: ${ours}` : why ? `(not adopted: ${why})` : '(new or unmapped: decide whether to adopt it)';
      console.log(`  ${folder}/  ${files.length} file(s) changed  ${where}`);
    }
    console.log(`  full diff: https://github.com/${repo}/compare/${src.commit.slice(0, 7)}...${head.slice(0, 7)}`);
  }
}
if (behind) console.log(`\n${behind} source(s) have changes to review. After syncing, update "commit" and "synced" in upstream.json.`);
