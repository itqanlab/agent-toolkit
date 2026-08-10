#!/usr/bin/env node
// build.mjs — generate the agent-toolkit site from the repository itself.
//
// Source of truth is the repo, never a hand-kept copy:
//   .claude-plugin/marketplace.json   catalog entries
//   skills/<name>/SKILL.md            frontmatter = data, body = instructions
//   skills/<name>/README.md           detail page body
//   site/data/agents.json             verified per-agent discovery paths
//
// Adding a skill and pushing rebuilds the site. There is nothing to update by hand.

import { readFileSync, writeFileSync, mkdirSync, readdirSync, existsSync, cpSync, rmSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { marked } from 'marked';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, '..');
const OUT = join(HERE, 'dist');

const SITE = {
  title: 'Itqan Agent Toolkit',
  domain: 'agent-toolkit.itqanlab.com',
  url: 'https://agent-toolkit.itqanlab.com',
  repo: 'https://github.com/itqanlab/agent-toolkit',
  org: 'https://github.com/itqanlab',
  marketplace: 'itqan',
  tagline: 'Write it once. Eight agents find it.',
};

/* ---------------------------------------------------------------- read repo */

const read = (p) => readFileSync(p, 'utf8');
const esc = (s = '') => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
  .replace(/>/g, '&gt;').replace(/"/g, '&quot;');

// Minimal frontmatter reader. The spec allows only scalars and a flat metadata
// map, so a full YAML parser would be more surface than the format needs.
function frontmatter(src) {
  if (!src.startsWith('---')) return { data: {}, body: src };
  const end = src.indexOf('\n---', 3);
  if (end === -1) return { data: {}, body: src };
  const raw = src.slice(4, end);
  const body = src.slice(end + 4).replace(/^\n/, '');
  const data = {};
  let mapKey = null;
  for (const line of raw.split('\n')) {
    if (!line.trim()) continue;
    const nested = line.match(/^\s+([A-Za-z0-9_-]+):\s*(.*)$/);
    if (nested && mapKey) {
      data[mapKey][nested[1]] = unquote(nested[2]);
      continue;
    }
    const m = line.match(/^([A-Za-z0-9_-]+):\s*(.*)$/);
    if (!m) continue;
    if (m[2] === '') { mapKey = m[1]; data[mapKey] = {}; }
    else { mapKey = null; data[m[1]] = unquote(m[2]); }
  }
  return { data, body };
}
const unquote = (v) => v.replace(/^["']|["']$/g, '').trim();

// Triggers are written into the description as: Triggers: 'a', 'b', 'c'.
// Pulling them out gives the catalog real search terms instead of invented tags.
function splitDescription(desc = '') {
  const i = desc.search(/Triggers?:/i);
  if (i === -1) return { summary: desc.trim(), triggers: [] };
  const summary = desc.slice(0, i).trim();
  const triggers = [...desc.slice(i).matchAll(/'([^']+)'/g)].map((m) => m[1]);
  return { summary, triggers };
}

// "Requires ffmpeg, and yt-dlp for URL sources." -> ['ffmpeg', 'yt-dlp']
function deps(compat = '') {
  const found = new Set();
  for (const m of compat.matchAll(/\b(ffmpeg|yt-dlp|python|node|uv|git|docker|jq|pandoc|imagemagick)\b/gi)) {
    found.add(m[1].toLowerCase());
  }
  return [...found];
}

const marketplace = JSON.parse(read(join(ROOT, '.claude-plugin', 'marketplace.json')));
const agentData = JSON.parse(read(join(HERE, 'data', 'agents.json')));

function loadSkills() {
  const dir = join(ROOT, 'skills');
  if (!existsSync(dir)) return [];
  return readdirSync(dir, { withFileTypes: true })
    .filter((e) => e.isDirectory() && existsSync(join(dir, e.name, 'SKILL.md')))
    .map((e) => {
      const base = join(dir, e.name);
      const { data } = frontmatter(read(join(base, 'SKILL.md')));
      const entry = (marketplace.plugins || []).find((p) => p.name === e.name) || {};
      const { summary, triggers } = splitDescription(data.description);
      const readme = existsSync(join(base, 'README.md')) ? read(join(base, 'README.md')) : '';
      return {
        type: 'skill',
        name: e.name,
        display: entry.displayName || data.name || e.name,
        summary,
        triggers,
        description: data.description || '',
        compatibility: data.compatibility || '',
        deps: deps(data.compatibility),
        license: data.license || entry.license || 'MIT',
        version: (data.metadata && data.metadata.version) || entry.version || '0.0.0',
        keywords: entry.keywords || [],
        category: entry.category || 'general',
        readme,
        agents: agentData.agents.length,
        source: `${SITE.repo}/tree/main/skills/${e.name}`,
      };
    });
}

function loadDir(kind, folder) {
  const dir = join(ROOT, folder);
  if (!existsSync(dir)) return [];
  return readdirSync(dir, { withFileTypes: true })
    .filter((e) => e.isDirectory())
    .map((e) => ({ type: kind, name: e.name }));
}

const skills = loadSkills();
const plugins = loadDir('plugin', 'plugins');
const servers = loadDir('mcp', 'mcp');
const catalog = [...skills, ...plugins, ...servers];
const counts = { skill: skills.length, plugin: plugins.length, mcp: servers.length };

/* ---------------------------------------------------------------- chrome */

const NAV = [
  { href: '/', label: 'overview' },
  { href: '/browse/', label: 'browse' },
  { href: '/agents/', label: 'agents' },
];

function tree(active) {
  const rows = NAV.map((n, i) => {
    const last = i === NAV.length - 1;
    const on = n.href === active;
    return `<a class="tree-node${on ? ' is-active' : ''}" href="${n.href}">
      <span class="tree-glyph">${last ? '└─' : '├─'}</span><span>${n.label}</span></a>`;
  }).join('');
  return `<nav class="tree" aria-label="Sections">
    <a class="tree-root" href="/"><span class="tree-mark"></span>agent-toolkit</a>
    ${rows}
    <a class="tree-node tree-out" href="${SITE.repo}"><span class="tree-glyph">  </span><span>github ↗</span></a>
  </nav>`;
}

function page({ title, desc, active, body, cls = '', og = '/og.png' }) {
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)}</title>
<meta name="description" content="${esc(desc)}">
<meta property="og:title" content="${esc(title)}">
<meta property="og:description" content="${esc(desc)}">
<meta property="og:type" content="website">
<meta property="og:url" content="${SITE.url}">
<meta property="og:image" content="${SITE.url}${og}">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@500;600;700&family=Inter:wght@400;500&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/style.css">
</head>
<body class="${cls}">
<a class="skip" href="#main">Skip to content</a>
<div class="shell">
<header class="rail">
  <a class="brand" href="/">
    <span class="brand-mark" aria-hidden="true"></span>
    <span class="brand-text"><b>ITQAN</b> LAB</span>
  </a>
  ${tree(active)}
  <p class="rail-foot">MIT · verified ${agentData.verified}</p>
</header>
<main id="main">${body}</main>
</div>
<script src="/app.js" type="module"></script>
</body>
</html>`;
}

/* ---------------------------------------------------------------- signature */

// The convergence apparatus. Eight vendor paths resolve into one neutral path;
// Claude Code breaks away to its own. This is the product thesis drawn to scale,
// so the geometry is derived from the data rather than hand-placed.
function convergence() {
  const list = agentData.agents;
  const neutral = list.filter((a) => a.neutral);
  const holdout = list.find((a) => !a.neutral);

  const H = 36;                     // row pitch
  const top = 12;
  const edge = 250;                 // right edge of the label column — wires start here
  const busX = 470;                 // the vertical bus every neutral wire joins
  const rows = list.map((a, i) => ({ ...a, y: top + i * H + H / 2 }));
  const hubY = top + (list.length * H) / 2;
  const ruleY = top + list.length * H + 46;
  const VB_H = ruleY + 66;

  const wires = rows.map((a, i) => {
    const y = a.y;
    const turn = Math.min(26, Math.abs(hubY - y));      // corner radius, clamped near the hub
    const dir = y < hubY ? 1 : -1;
    const d = a.neutral
      ? `M ${edge + 12} ${y} H ${busX - turn} Q ${busX} ${y} ${busX} ${y + turn * dir} V ${hubY}`
      : `M ${edge + 12} ${y} H ${busX + 44}`;
    return `<path class="wire ${a.neutral ? 'wire-on' : 'wire-off'}" data-agent="${a.id}"
      d="${d}" style="--i:${i}"/>`;
  }).join('');

  // Labels are right-aligned so every wire leaves from the same vertical edge.
  const labels = rows.map((a, i) => `
    <g class="wlabel" data-agent="${a.id}" style="--i:${i}">
      <text class="wlabel-name" text-anchor="end" x="${edge}" y="${a.y - 3}">${esc(a.name)}</text>
      <text class="wlabel-path" text-anchor="end" x="${edge}" y="${a.y + 11}">${esc(a.userPaths[a.neutral ? 1 : 0] || a.userPaths[0])}</text>
    </g>`).join('');

  return `<figure class="rig" aria-labelledby="rig-cap">
  <svg viewBox="0 0 660 ${VB_H}" role="img"
       aria-label="Eight agents. Seven resolve to the shared path ${agentData.neutral}; Claude Code reads its own directory and installs from the marketplace.">
    <g class="wires">${wires}</g>
    <g class="wlabels">${labels}</g>
    <circle class="hub-dot" cx="${busX}" cy="${hubY}" r="4.5"/>
    <path class="wire wire-trunk" d="M ${busX} ${hubY} V ${ruleY} H 4"/>
    <g class="dest dest-on" transform="translate(4 ${ruleY})">
      <text class="dest-path" x="0" y="26">${esc(agentData.neutral)}</text>
      <text class="dest-meta" x="0" y="46">${neutral.length} of ${list.length} agents resolve here</text>
    </g>
    <g class="dest dest-off" transform="translate(${busX + 54} ${rows.find((r) => !r.neutral).y})">
      <text class="dest-path" x="0" y="0">${esc(holdout.userPaths[0])}</text>
      <text class="dest-meta" x="0" y="15">marketplace instead</text>
    </g>
  </svg>
  <figcaption id="rig-cap" class="rig-cap">
    Discovery paths, verified ${agentData.verified}. Hover a row to trace it.
  </figcaption>
</figure>`;
}

/* ---------------------------------------------------------------- cards */

function card(item) {
  if (item.type !== 'skill') {
    return `<article class="card card-soon"><header class="card-head">
      <h3 class="card-name">${esc(item.name)}</h3><span class="tag">${item.type}</span>
    </header></article>`;
  }
  return `<a class="card" href="/s/${item.name}/" data-name="${esc(item.name)}"
     data-type="skill" data-deps="${esc(item.deps.join(' '))}"
     data-search="${esc([item.name, item.summary, ...item.triggers, ...item.keywords].join(' ').toLowerCase())}">
  <header class="card-head">
    <h3 class="card-name">${esc(item.name)}</h3>
    <span class="card-v">v${esc(item.version)}</span>
  </header>
  <p class="card-sum">${esc(item.summary)}</p>
  <footer class="card-foot">
    <span class="card-agents"><b>${item.agents}</b>/8 agents</span>
    ${item.deps.map((d) => `<span class="tag">${esc(d)}</span>`).join('')}
  </footer>
</a>`;
}

/* ---------------------------------------------------------------- pages */

function home() {
  const featured = skills.slice(0, 6).map(card).join('');
  return `
<section class="hero">
  <div class="hero-copy">
    <p class="eyebrow">Agent Skills · open standard</p>
    <h1 class="hero-h">Write it once.<br><em>Eight agents</em><br>find it.</h1>
    <p class="lede">One skill directory. No forks, no per-agent rewrites, no build step.
      Drop it in the shared path and every conformant agent picks it up.</p>
    <div class="cmds">
      <button class="cmd" data-copy="./scripts/install.sh">
        <span class="cmd-k">any agent</span>
        <code>./scripts/install.sh</code><span class="cmd-c">copy</span>
      </button>
      <button class="cmd" data-copy="/plugin marketplace add itqanlab/agent-toolkit">
        <span class="cmd-k">claude code</span>
        <code>/plugin marketplace add itqanlab/agent-toolkit</code><span class="cmd-c">copy</span>
      </button>
    </div>
  </div>
  ${convergence()}
</section>

<section class="band">
  <h2 class="h2"><span class="h2-n">01</span> The catalog</h2>
  <p class="band-lede">Generated from the repository on every push. What you see here is what ships.</p>
  <div class="grid">${featured}</div>
  <p class="more"><a href="/browse/">Browse all ${catalog.length} →</a></p>
</section>

<section class="band band-split">
  <div>
    <h2 class="h2"><span class="h2-n">02</span> Three tiers</h2>
    <p class="band-lede">Split by how far each one travels, not by taste.</p>
  </div>
  <dl class="tiers">
    <div class="tier"><dt>Skills</dt><dd><b>${counts.skill}</b> · portable to all 8 agents. Instructions plus scripts, read by every conformant agent unchanged.</dd></div>
    <div class="tier"><dt>MCP servers</dt><dd><b>${counts.mcp}</b> · any MCP client. Live tool surfaces with their own credentials and typed contracts.</dd></div>
    <div class="tier"><dt>Plugins</dt><dd><b>${counts.plugin}</b> · Claude Code. Subagents, hooks and commands — components the standard has no concept of.</dd></div>
  </dl>
</section>

<footer class="foot">
  <p><a href="${SITE.repo}">github.com/itqanlab/agent-toolkit</a></p>
  <p>MIT · <a href="${SITE.org}">Itqan Lab</a></p>
</footer>`;
}

function browse() {
  return `
<section class="head">
  <h1 class="page-h">Browse</h1>
  <p class="lede">${catalog.length} in the catalog. Search matches names, summaries and trigger phrases.</p>
</section>
<div class="filters">
  <label class="search">
    <span class="sr">Search the catalog</span>
    <input id="q" type="search" placeholder="search — try &quot;video&quot; or &quot;transcript&quot;" autocomplete="off">
  </label>
  <div class="chips" role="group" aria-label="Filter by type">
    <button class="chip is-on" data-type="all">all <b>${catalog.length}</b></button>
    <button class="chip" data-type="skill">skills <b>${counts.skill}</b></button>
    <button class="chip" data-type="mcp">mcp <b>${counts.mcp}</b></button>
    <button class="chip" data-type="plugin">plugins <b>${counts.plugin}</b></button>
  </div>
</div>
<div class="grid" id="results">${catalog.map(card).join('')}</div>
<p class="empty" id="empty" hidden>Nothing matches that. <button class="linkish" id="clear">Clear filters</button></p>
<footer class="foot"><p><a href="${SITE.repo}">Propose a skill →</a></p></footer>`;
}

function agentsPage() {
  const rows = agentData.agents.map((a) => `
  <article class="agent ${a.neutral ? '' : 'agent-holdout'}">
    <header class="agent-head">
      <h3>${esc(a.name)}</h3>
      <span class="agent-vendor">${esc(a.vendor)}</span>
      <span class="agent-state">${a.neutral ? 'shared path' : 'own path'}</span>
    </header>
    <dl class="agent-paths">
      <dt>user</dt><dd>${a.userPaths.map((p) => `<code>${esc(p)}</code>`).join('')}</dd>
      <dt>project</dt><dd>${a.projectPaths.map((p) => `<code>${esc(p)}</code>`).join('')}</dd>
    </dl>
    <p class="agent-note">${esc(a.note)}</p>
    <p class="agent-doc"><a href="${a.docs}">Vendor documentation ↗</a></p>
  </article>`).join('');
  return `
<section class="head">
  <h1 class="page-h">Agents</h1>
  <p class="lede">Discovery paths read from each vendor's own documentation on ${agentData.verified}.
    Seven of eight read <code>${esc(agentData.neutral)}</code>. Claude Code does not, so it gets the marketplace.</p>
</section>
<div class="agents">${rows}</div>
<footer class="foot"><p><a href="${SITE.repo}/blob/main/docs/COMPATIBILITY.md">Full matrix with sources →</a></p></footer>`;
}

function skillPage(s) {
  const body = marked.parse(s.readme.replace(/^#\s+.*\n/, ''));
  return `
<section class="head head-skill">
  <p class="eyebrow"><a href="/browse/">catalog</a> / skill</p>
  <h1 class="page-h mono">${esc(s.name)}</h1>
  <p class="lede">${esc(s.summary)}</p>
  <div class="specs">
    <div><dt>version</dt><dd>${esc(s.version)}</dd></div>
    <div><dt>agents</dt><dd>${s.agents}/8</dd></div>
    <div><dt>requires</dt><dd>${s.deps.length ? s.deps.map((d) => esc(d)).join(' · ') : 'nothing'}</dd></div>
    <div><dt>license</dt><dd>${esc(s.license)}</dd></div>
  </div>
  <div class="cmds">
    <button class="cmd" data-copy="./scripts/install.sh ${s.name}">
      <span class="cmd-k">any agent</span><code>./scripts/install.sh ${esc(s.name)}</code><span class="cmd-c">copy</span>
    </button>
    <button class="cmd" data-copy="/plugin install ${s.name}@${SITE.marketplace}">
      <span class="cmd-k">claude code</span><code>/plugin install ${esc(s.name)}@${SITE.marketplace}</code><span class="cmd-c">copy</span>
    </button>
  </div>
</section>
${s.triggers.length ? `<section class="band">
  <h2 class="h2">Say any of this</h2>
  <ul class="triggers">${s.triggers.map((t) => `<li>“${esc(t)}”</li>`).join('')}</ul>
  <p class="band-lede">The agent matches these on its own. No command to remember.</p>
</section>` : ''}
<section class="band prose">${body}</section>
<footer class="foot"><p><a href="${s.source}">Source on GitHub ↗</a></p></footer>`;
}

/* ---------------------------------------------------------------- og cards */

function ogSvg({ kicker, title, sub }) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <rect width="1200" height="630" fill="#FAFAF9"/>
  <rect x="0" y="0" width="1200" height="10" fill="#d97706"/>
  <g font-family="JetBrains Mono, monospace">
    <text x="76" y="150" font-size="26" fill="#71717A" letter-spacing="2">${esc(kicker)}</text>
  </g>
  <g font-family="Outfit, Inter, sans-serif" font-weight="700">
    <text x="76" y="290" font-size="82" fill="#09090B">${esc(title)}</text>
  </g>
  <g font-family="Inter, sans-serif">
    <text x="76" y="360" font-size="30" fill="#3F3F46">${esc(sub)}</text>
  </g>
  <g font-family="JetBrains Mono, monospace" font-size="24" fill="#71717A">
    <text x="76" y="540">~/.agents/skills/</text>
    <rect x="76" y="556" width="330" height="3" fill="#d4a853"/>
    <text x="76" y="592" font-size="20" fill="#A1A1AA">agent-toolkit.itqanlab.com</text>
  </g>
  <g transform="translate(1010 470)">
    <rect width="114" height="114" rx="26" fill="#09090B"/>
    <circle cx="57" cy="57" r="34" fill="none" stroke="#d4a853" stroke-width="5"/>
  </g>
</svg>`;
}

/* ---------------------------------------------------------------- emit */

rmSync(OUT, { recursive: true, force: true });
mkdirSync(OUT, { recursive: true });

const write = (rel, content) => {
  const p = join(OUT, rel);
  mkdirSync(dirname(p), { recursive: true });
  writeFileSync(p, content);
};

write('index.html', page({
  title: `${SITE.title} — ${SITE.tagline}`,
  desc: 'Portable Agent Skills, MCP servers and plugins. One directory, eight agents.',
  active: '/', body: home(), cls: 'p-home',
}));

write('browse/index.html', page({
  title: `Browse — ${SITE.title}`,
  desc: `${catalog.length} skills, MCP servers and plugins for AI coding agents.`,
  active: '/browse/', body: browse(), cls: 'p-browse', og: '/og-browse.png',
}));

write('agents/index.html', page({
  title: `Agents — ${SITE.title}`,
  desc: 'Verified skill discovery paths for eight AI coding agents.',
  active: '/agents/', body: agentsPage(), cls: 'p-agents', og: '/og-agents.png',
}));

for (const s of skills) {
  write(`s/${s.name}/index.html`, page({
    title: `${s.name} — ${SITE.title}`,
    desc: s.summary,
    active: '/browse/', body: skillPage(s), cls: 'p-skill', og: `/og-${s.name}.png`,
  }));
  write(`og-${s.name}.svg`, ogSvg({ kicker: 'SKILL', title: s.name, sub: s.summary.slice(0, 64) }));
}

write('og.svg', ogSvg({ kicker: 'ITQAN LAB', title: 'Agent Toolkit', sub: SITE.tagline }));
write('og-browse.svg', ogSvg({ kicker: 'CATALOG', title: 'Browse', sub: `${catalog.length} tools for AI coding agents` }));
write('og-agents.svg', ogSvg({ kicker: 'COMPATIBILITY', title: 'Eight agents', sub: 'Verified discovery paths' }));

write('CNAME', `${SITE.domain}\n`);
write('.nojekyll', '');
write('robots.txt', `User-agent: *\nAllow: /\nSitemap: ${SITE.url}/sitemap.xml\n`);
write('sitemap.xml', `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${['/', '/browse/', '/agents/', ...skills.map((s) => `/s/${s.name}/`)]
    .map((u) => `  <url><loc>${SITE.url}${u}</loc></url>`).join('\n')}
</urlset>`);

cpSync(join(HERE, 'static'), OUT, { recursive: true });

console.log(`built → site/dist`);
console.log(`  pages   ${3 + skills.length}`);
console.log(`  catalog ${catalog.length} (${counts.skill} skill · ${counts.mcp} mcp · ${counts.plugin} plugin)`);
console.log(`  agents  ${agentData.agents.length}`);
