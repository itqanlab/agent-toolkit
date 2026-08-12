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
  tagline: 'Just ask. Your agent has the tool.',
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
//
// The separator is matched loosely. A skill that writes "Triggers," instead of
// "Triggers:" is following the convention in spirit, and silently dropping its
// whole trigger list — which is what the page leads with — is far worse than
// accepting a comma. validate.sh warns when the canonical form is not used.
function splitDescription(desc = '') {
  const i = desc.search(/Triggers?\s*[:,—-]/i);
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
    <a class="tree-node tree-out" href="${SITE.repo}" target="_blank" rel="noopener"><span class="tree-glyph">  </span><span>github ↗</span></a>
  </nav>`;
}

// Applied before first paint so a saved theme never flashes the wrong ground.
const THEME_BOOT = `<script>(function(){try{var t=localStorage.getItem('theme');if(t==='light'||t==='dark')document.documentElement.setAttribute('data-theme',t);}catch(e){}})()</script>`;

function page({ title, desc, active, body, cls = '', og = '/og.png', path = '/', jsonld = [] }) {
  const canonical = `${SITE.url}${path}`;
  const graph = [...jsonld, ORG_LD, breadcrumbLd(path, title)].filter(Boolean);
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)}</title>
<meta name="description" content="${esc(desc)}">
<link rel="canonical" href="${canonical}">
<meta name="author" content="Itqan Lab">
<meta name="theme-color" content="#FAFAF9" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#09090B" media="(prefers-color-scheme: dark)">
<meta property="og:site_name" content="${esc(SITE.title)}">
<meta property="og:title" content="${esc(title)}">
<meta property="og:description" content="${esc(desc)}">
<meta property="og:type" content="website">
<meta property="og:url" content="${canonical}">
<meta property="og:image" content="${SITE.url}${og}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="${esc(title)}">
<meta name="twitter:description" content="${esc(desc)}">
<meta name="twitter:image" content="${SITE.url}${og}">
<link rel="icon" href="/logo.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/logo.svg">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@500;600;700&family=Inter:wght@400;500&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/style.css">
<script type="application/ld+json">${JSON.stringify(graph.length === 1 ? graph[0] : { '@context': 'https://schema.org', '@graph': graph.map(stripCtx) })}</script>
${THEME_BOOT}
</head>
<body class="${cls}">
<a class="skip" href="#main">Skip to content</a>
<div class="shell">
<header class="rail">
  <a class="brand" href="/" aria-label="${esc(SITE.title)} — by Itqan Lab">
    <img class="brand-mark" src="/logo.svg" alt="" width="26" height="26">
    <span class="brand-text"><b>ITQAN</b> LAB</span>
  </a>
  ${tree(active)}
  <div class="rail-foot">
    <button class="theme" id="theme" type="button" aria-label="Colour theme">
      <span class="theme-dot" aria-hidden="true"></span><span id="theme-label">auto</span>
    </button>
    <p class="rail-meta">MIT · verified ${agentData.verified}</p>
  </div>
</header>
<main id="main">${body}</main>
</div>
<script src="/app.js" type="module"></script>
</body>
</html>`;
}

const stripCtx = (o) => { const { '@context': _c, ...rest } = o; return rest; };

/* ------------------------------------------------------------ structured data */

const ORG_LD = {
  '@context': 'https://schema.org',
  '@type': 'Organization',
  '@id': `${SITE.url}#org`,
  name: 'Itqan Lab',
  alternateName: 'إتقان لاب',
  description: 'Design and technology studio. Itqan (إتقان) is the Arabic word for mastery — doing a thing precisely and completely.',
  url: 'https://itqanlab.com',
  logo: `${SITE.url}/logo.svg`,
  sameAs: ['https://github.com/itqanlab'],
};

function breadcrumbLd(path, title) {
  if (path === '/') return null;
  const parts = path.split('/').filter(Boolean);
  const items = [{ '@type': 'ListItem', position: 1, name: 'Home', item: SITE.url }];
  let acc = '';
  parts.forEach((p, i) => {
    acc += `/${p}`;
    items.push({
      '@type': 'ListItem', position: i + 2,
      name: i === parts.length - 1 ? title.split(' — ')[0] : p,
      item: `${SITE.url}${acc}/`,
    });
  });
  return { '@context': 'https://schema.org', '@type': 'BreadcrumbList', itemListElement: items };
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
    <span class="card-agents">portable</span>
    ${item.deps.map((d) => `<span class="tag">${esc(d)}</span>`).join('')}
  </footer>
</a>`;
}

/* ---------------------------------------------------------------- pages */

function home() {
  const featured = skills.slice(0, 6).map(card).join('');
  // The trigger phrases are real: each skill declares them in its own frontmatter.
  // They are also the actual interface, so they belong in the hero.
  const asks = skills.flatMap((s) => s.triggers.filter((t) => t.length > 12 && !t.startsWith('/'))
    .map((t) => ({ say: t, skill: s.name, deps: s.deps })))
    .sort((a, b) => b.say.length - a.say.length);
  const first = asks[0] || { say: 'watch this video and tell me why the hook works', skill: skills[0]?.name || '', deps: [] };

  return `
<section class="hero">
  <div class="hero-copy">
    <p class="eyebrow">A toolkit for AI coding agents</p>
    <h1 class="hero-h">Just ask.<br>Your agent<br><em>has the tool.</em></h1>
    <p class="lede">Install once and your agent picks up new abilities it did not have before —
      no commands to memorise, no wiring. Ask in plain language and it reaches for the right one.
      Works in Claude Code, Codex, Cursor, Gemini CLI, Copilot and
      ${agentData.ecosystem.approx} more, because it is built on an open standard.</p>
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

  <figure class="say" data-asks='${esc(JSON.stringify(asks))}'>
    <div class="say-turn">
      <span class="say-who">you say</span>
      <p class="say-line" id="say-line">${esc(first.say)}</p>
    </div>
    <div class="say-turn say-turn-agent">
      <span class="say-who">your agent reaches for</span>
      <p class="say-skill"><a id="say-skill" href="/s/${esc(first.skill)}/">${esc(first.skill)}</a></p>
      <p class="say-deps" id="say-deps">${first.deps.map((d) => esc(d)).join(' · ')}</p>
    </div>
    <figcaption class="say-cap">Real trigger phrases, read from each skill's own frontmatter.</figcaption>
  </figure>
</section>

<section class="band">
  <h2 class="h2"><span class="h2-n">01</span> What's in the bag</h2>
  <p class="band-lede">Generated from the repository on every push. What you see here is what ships.</p>
  <div class="grid">${featured}</div>
  <p class="more"><a href="/browse/">Browse all ${catalog.length} →</a></p>
</section>

<section class="band band-split">
  <div>
    <h2 class="h2"><span class="h2-n">02</span> Who it's for</h2>
    <p class="band-lede">If you already work with an AI coding agent, this is a bag of tools it can
      reach into. If you build them, it is a worked example of the standard.</p>
  </div>
  <dl class="tiers">
    <div class="tier"><dt>You use one agent</dt><dd>Install once. Your agent gains abilities you can ask for in plain language, and nothing changes about how you work.</dd></div>
    <div class="tier"><dt>You switch between agents</dt><dd>The same tools follow you. Move from Claude Code to Cursor to Codex and your setup comes with you, unchanged.</dd></div>
    <div class="tier"><dt>You work in a team</dt><dd>Commit the skills to a repository and everyone who clones it gets the same tools, whichever agent each person prefers.</dd></div>
    <div class="tier"><dt>You build tooling</dt><dd>Every skill here is a working reference for the spec, with a validator that enforces portability before a commit lands.</dd></div>
  </dl>
</section>

<section class="band">
  <h2 class="h2"><span class="h2-n">03</span> Why it works everywhere</h2>
  <p class="band-lede">A skill is a folder with a <code>SKILL.md</code> in it. Agents look for those
    folders in a shared location, so one copy serves all of them. Here is where each one actually looks.</p>
  ${convergence()}
</section>

<section class="band band-split">
  <div>
    <h2 class="h2"><span class="h2-n">04</span> Three tiers</h2>
    <p class="band-lede">Split by how far each one travels, not by taste.</p>
  </div>
  <dl class="tiers">
    <div class="tier"><dt>Skills</dt><dd><b>${counts.skill}</b> · every conformant agent. Instructions plus scripts, read unchanged wherever the standard is implemented.</dd></div>
    <div class="tier"><dt>MCP servers</dt><dd><b>${counts.mcp}</b> · any MCP client. Live tool surfaces with their own credentials and typed contracts.</dd></div>
    <div class="tier"><dt>Plugins</dt><dd><b>${counts.plugin}</b> · Claude Code. Subagents, hooks and commands — components the standard has no concept of.</dd></div>
  </dl>
</section>

<section class="band">
  <h2 class="h2"><span class="h2-n">05</span> Questions</h2>
  <div class="faq">${FAQ.map((f, i) => `
    <details class="qa"${i === 0 ? ' open' : ''}>
      <summary><h3>${esc(f.q)}</h3></summary>
      <div class="qa-a">${f.a}</div>
    </details>`).join('')}
  </div>
</section>

${colophon()}`;
}

// Answers are written to stand alone. Each one should survive being lifted out
// of the page and quoted on its own, which is also how AI search reads them.
const FAQ = [
  {
    q: 'What is an agent skill?',
    a: `<p>An agent skill is a folder containing a <code>SKILL.md</code> file: YAML frontmatter with a
      <code>name</code> and <code>description</code>, followed by instructions in Markdown, plus optional
      <code>scripts/</code>, <code>references/</code> and <code>assets/</code> directories. The agent loads
      only the name and description at startup, and reads the full instructions only when a task matches.
      That progressive loading is why an agent can keep many skills available at almost no context cost.
      The format is defined by the Agent Skills specification, an open standard stewarded by the Agentic
      AI Foundation and implemented by ${agentData.ecosystem.approx} tools.</p>`,
  },
  {
    q: 'Do I need a different version of a skill for each agent?',
    a: `<p>No. A skill written to the specification is a single folder that every conformant agent reads
      unchanged. The two rules that keep it portable are to reference bundled files by paths relative to the
      skill root — <code>scripts/watch.sh</code>, never an absolute path — and to keep vendor-specific
      syntax out of the instructions, since the body is read verbatim by every agent. Every skill in this
      toolkit is checked against both rules automatically before it can be committed.</p>`,
  },
  {
    q: 'Where do agents look for skills on disk?',
    a: `<p>Most read <code>~/.agents/skills/</code> at the user level and <code>.agents/skills/</code> inside
      a project — a vendor-neutral path that several agents give precedence over their own directories.
      Of the ${agentData.agents.length} agents whose documentation we verified on ${agentData.verified},
      ${agentData.agents.filter((a) => a.neutral).length} read it. Claude Code is the exception: it reads
      <code>~/.claude/skills/</code>, <code>.claude/skills/</code> and installed plugins only, which is why
      it installs from a plugin marketplace here instead.</p>`,
  },
  {
    q: 'How is this different from an MCP server?',
    a: `<p>A skill is procedural knowledge — instructions and scripts, loaded on demand, with no process
      running. An MCP server is a live tool surface: it runs, holds credentials, and exposes typed tools over
      a protocol. Reach for MCP when the capability needs a persistent connection or a typed contract; reach
      for a skill when a Markdown file and a shell script would do the job. This toolkit ships both, and
      keeps them in separate tiers because they travel differently.</p>`,
  },
  {
    q: 'Is it free, and can I use it commercially?',
    a: `<p>Yes. Everything here is MIT licensed and free to use, modify and redistribute, including in
      commercial work. There is no account, no telemetry, and no API key required by the toolkit itself —
      individual skills declare their own dependencies, such as <code>ffmpeg</code>, in a
      <code>compatibility</code> field you can read before installing.</p>`,
  },
];

// Quiet authorship. Who made this, why the name means what it means, and how it
// was built — the kind of thing a developer reads at the bottom and remembers.
function colophon() {
  return `
<section class="colophon">
  <div class="colo-mark"><img src="/logo.svg" alt="Itqan Lab" width="44" height="44"></div>
  <div class="colo-body">
    <p class="colo-lead">Built at <a href="https://itqanlab.com" target="_blank" rel="noopener">Itqan Lab</a>, a design and technology studio.</p>
    <p class="colo-ar"><span lang="ar" dir="rtl">إتقان</span> — <em>itqan</em>, the Arabic word for mastery:
      doing a thing precisely, and completely.</p>
    <p class="colo-meta">Open source under MIT · agent paths re-verified ${agentData.verified} ·
      this site is generated from the repository on every push.</p>
  </div>
</section>
<footer class="foot">
  <p><a href="${SITE.repo}" target="_blank" rel="noopener">github.com/itqanlab/agent-toolkit</a></p>
  <p><a href="https://agentskills.io/specification" target="_blank" rel="noopener">Agent Skills spec</a> · <a href="/llms.txt">llms.txt</a></p>
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
<p class="more"><a href="${SITE.repo}/issues" target="_blank" rel="noopener">Propose a skill →</a></p>
${colophon()}`;
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
    <p class="agent-doc"><a href="${a.docs}" target="_blank" rel="noopener">Vendor documentation ↗</a></p>
  </article>`).join('');
  const onCount = agentData.agents.filter((a) => a.neutral).length;
  return `
<section class="head">
  <h1 class="page-h">Agents</h1>
  <p class="lede">Agent Skills is an open standard, so a conformant skill runs in any tool that implements
    it. Below are the ${agentData.agents.length} agents whose discovery paths we read from the vendor's own
    documentation and verified on ${agentData.verified}. ${onCount} of them read
    <code>${esc(agentData.neutral)}</code>; Claude Code does not, so it installs from the marketplace.</p>
</section>
<h2 class="sec-h"><span class="sec-n">Verified</span> paths documented and sourced</h2>
<div class="agents">${rows}</div>

<h2 class="sec-h"><span class="sec-n">Also compatible</span> implements the same standard</h2>
<p class="band-lede">These tools read the same <code>SKILL.md</code>. We have not verified their install
  paths ourselves, so they are listed rather than documented — follow the vendor link for placement.</p>
<ul class="compat">${agentData.compatible.map((c) => `
  <li><a href="${c.url}" target="_blank" rel="noopener"><span class="compat-n">${esc(c.name)}</span><span class="compat-v">${esc(c.vendor)}</span></a></li>`).join('')}
</ul>
<p class="more"><a href="${agentData.ecosystem.showcase}" target="_blank" rel="noopener">Full ecosystem showcase →</a></p>
${colophon()}`;
}

// Split a README on its H2s so sections can be placed and styled deliberately
// instead of pouring the whole file onto the page as one column of prose.
function sections(md) {
  const out = [];
  const parts = md.replace(/^#\s+.*\n/, '').split(/\n(?=##\s+)/);
  for (const p of parts) {
    const m = p.match(/^##\s+(.+)\n([\s\S]*)$/);
    if (m) out.push({ title: m[1].trim(), body: m[2].trim() });
    else if (p.trim()) out.push({ title: '', body: p.trim() });
  }
  return out;
}

const slug = (t) => t.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

// Pull the fenced blocks out of an Examples section, each with the comment line
// above it as its label. Reads as a set of recipes rather than a code dump.
function recipes(body) {
  const out = [];
  // A single fenced block usually holds several examples, each introduced by a
  // comment line. Each comment starts a new card rather than all of them
  // collapsing into one.
  for (const m of body.matchAll(/```(?:bash|sh)?\n([\s\S]*?)```/g)) {
    let label = '';
    let cmds = [];
    const flush = () => {
      if (cmds.length) out.push({ label, cmd: cmds.join('\n') });
      cmds = [];
    };
    for (const ln of m[1].trim().split('\n')) {
      const t = ln.trim();
      if (t.startsWith('#')) { flush(); label = t.replace(/^#\s?/, ''); continue; }
      if (t) cmds.push(t);
    }
    flush();
  }
  return out;
}

function skillPage(s) {
  const secs = sections(s.readme);
  const find = (re) => secs.find((x) => re.test(x.title));
  const setup = find(/^setup/i);
  const usage = find(/^usage/i);
  const examples = find(/^example/i);
  const how = find(/^how it works/i);
  const limits = find(/^limit/i);
  const shown = new Set([setup, usage, examples, how, limits, find(/^install/i), find(/^license/i)].filter(Boolean));
  const rest = secs.filter((x) => x.title && !shown.has(x));

  // The options table is already structured data in the README; render it as a
  // table rather than letting it arrive as generic prose.
  const optTable = usage && usage.body.match(/\|[\s\S]*\|/);

  // "Say this" leads. Most people arriving here will never type a command —
  // they ask their agent — so the page opens with the sentences that work, and
  // the install step follows for whoever is actually setting the machine up.
  const nav = [
    s.triggers.length ? ['say', 'Say this'] : null,
    ['install', 'Install'],
    setup ? ['requirements', 'Requirements'] : null,
    optTable ? ['options', 'Options'] : null,
    examples ? ['examples', 'Examples'] : null,
    how ? ['how', 'How it works'] : null,
    limits ? ['limits', 'Limits'] : null,
  ].filter(Boolean);

  const body = marked.parse(rest.map((r) => `## ${r.title}\n${r.body}`).join('\n\n'));
  return `
<section class="head head-skill">
  <p class="eyebrow"><a href="/browse/">catalog</a> / skill</p>
  <h1 class="page-h mono">${esc(s.name)}</h1>
  <p class="lede">${esc(s.summary)}</p>
  <div class="specs">
    <div><dt>version</dt><dd>${esc(s.version)}</dd></div>
    <div><dt>works in</dt><dd>every conformant agent</dd></div>
    <div><dt>needs</dt><dd>${s.deps.length ? s.deps.map((d) => esc(d)).join(' · ') : 'nothing'}</dd></div>
    <div><dt>cost</dt><dd>free · no API key</dd></div>
    <div><dt>license</dt><dd>${esc(s.license)}</dd></div>
  </div>
</section>

<nav class="jump" aria-label="On this page">
  ${nav.map(([id, label]) => `<a href="#${id}">${esc(label)}</a>`).join('')}
</nav>

${s.triggers.length ? `<section class="band" id="say">
  <h2 class="sec-h"><span class="sec-n">Say this</span> you do not type commands, you ask</h2>
  <ul class="triggers">${s.triggers.map((t) => `<li>“${esc(t)}”</li>`).join('')}</ul>
  <p class="band-lede">Once it is installed, that is the whole interface. Your agent picks the skill
  up on its own and runs whatever it needs to. The commands further down are there for anyone who
  would rather drive it themselves.</p>
</section>` : ''}

<section class="band" id="install">
  <h2 class="sec-h"><span class="sec-n">Install</span> pick your agent</h2>
  <div class="cmds cmds-wide">
    <button class="cmd" data-copy="./scripts/install.sh ${s.name}">
      <span class="cmd-k">any agent</span><code>./scripts/install.sh ${esc(s.name)}</code><span class="cmd-c">copy</span>
    </button>
    <button class="cmd" data-copy="/plugin install ${s.name}@${SITE.marketplace}">
      <span class="cmd-k">claude code</span><code>/plugin install ${esc(s.name)}@${SITE.marketplace}</code><span class="cmd-c">copy</span>
    </button>
  </div>
</section>

${setup ? `<section class="band" id="requirements">
  <h2 class="sec-h"><span class="sec-n">Requirements</span> what to install, and why</h2>
  <div class="prose prose-tight">${marked.parse(setup.body)}</div>
</section>` : ''}

${optTable ? `<section class="band" id="options">
  <h2 class="sec-h"><span class="sec-n">Options</span> every flag</h2>
  <div class="prose prose-tight">${marked.parse(optTable[0])}</div>
</section>` : ''}

${examples ? `<section class="band" id="examples">
  <h2 class="sec-h"><span class="sec-n">Examples</span> copy and go</h2>
  <div class="recipes">${recipes(examples.body).map((r) => `
    <button class="recipe" data-copy="${esc(r.cmd)}">
      <span class="recipe-label">${esc(r.label || 'run it')}</span>
      <code class="recipe-cmd">${esc(r.cmd)}</code>
      <span class="recipe-copy">copy</span>
    </button>`).join('')}
  </div>
</section>` : ''}

${how ? `<section class="band" id="how">
  <h2 class="sec-h"><span class="sec-n">How it works</span> step by step</h2>
  <div class="prose prose-tight steps">${marked.parse(how.body)}</div>
</section>` : ''}

${limits ? `<section class="band" id="limits">
  <h2 class="sec-h"><span class="sec-n">Limits</span> what it will not do</h2>
  <div class="prose prose-tight">${marked.parse(limits.body)}</div>
</section>` : ''}

${rest.length ? `<section class="band prose">${body}</section>` : ''}

<p class="more"><a href="${s.source}" target="_blank" rel="noopener">Source on GitHub ↗</a></p>
${colophon()}`;
}

/* ---------------------------------------------------------------- og cards */

// The real mark (rounded square, ring, four compass dots, the ain glyph) —
// inlined from site/static/logo.svg so OG cards carry the actual logo instead
// of a lookalike square-and-circle placeholder.
const LOGO_MARK = `
  <rect width="280" height="280" rx="56" fill="#09090B"/>
  <circle cx="140" cy="140" r="104" fill="none" stroke="#d4a853" stroke-width="12"/>
  <circle cx="140" cy="36" r="9" fill="#d4a853"/>
  <circle cx="244" cy="140" r="9" fill="#d4a853"/>
  <circle cx="140" cy="244" r="9" fill="#d4a853"/>
  <circle cx="36" cy="140" r="9" fill="#d4a853"/>
  <g transform="translate(140,138) scale(1.05)">
    <path d="M-10 -44 C-10 -44,-16 -10,-5 14 C0 28,10 36,10 36" fill="none" stroke="#d4a853" stroke-width="15" stroke-linecap="round" stroke-linejoin="round"/>
    <path d="M-5 14 C-5 14,14 8,22 -6" fill="none" stroke="#d4a853" stroke-width="15" stroke-linecap="round" stroke-linejoin="round"/>
    <circle cx="-10" cy="-50" r="12.3" fill="#d4a853"/>
  </g>`;

// Greedy word wrap by character budget — good enough for a single sans-serif
// weight at a fixed size. Keeps whole words; never slices mid-word like the
// old fixed-length slice() did (it cut "natively" down to "nativel").
function wrapWords(text, maxChars, maxLines) {
  const words = text.trim().split(/\s+/);
  const lines = [];
  let line = '';
  for (const w of words) {
    const next = line ? `${line} ${w}` : w;
    if (next.length > maxChars && line) { lines.push(line); line = w; }
    else line = next;
    if (lines.length === maxLines - 1 && line.length > maxChars) break;
  }
  if (line) lines.push(line);
  if (lines.length > maxLines) {
    lines.length = maxLines;
    lines[maxLines - 1] = lines[maxLines - 1].replace(/\s*\S*$/, '').trim() + '…';
  }
  return lines;
}

function ogSvg({ kicker, title, sub }) {
  const subLines = wrapWords(sub, 54, 2);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <rect width="1200" height="630" fill="#FAFAF9"/>
  <rect x="0" y="0" width="1200" height="10" fill="#d97706"/>
  <g font-family="JetBrains Mono, monospace">
    <text x="76" y="150" font-size="26" fill="#71717A" letter-spacing="2">${esc(kicker)}</text>
  </g>
  <g font-family="Outfit, Inter, sans-serif" font-weight="700">
    <text x="76" y="290" font-size="82" fill="#09090B">${esc(title)}</text>
  </g>
  <g font-family="Inter, sans-serif" font-size="30" fill="#3F3F46">
    ${subLines.map((l, i) => `<text x="76" y="${360 + i * 42}">${esc(l)}</text>`).join('\n    ')}
  </g>
  <g font-family="JetBrains Mono, monospace" font-size="24" fill="#71717A">
    <text x="76" y="540">~/.agents/skills/</text>
    <rect x="76" y="556" width="330" height="3" fill="#d4a853"/>
    <text x="76" y="592" font-size="20" fill="#A1A1AA">agent-toolkit.itqanlab.com</text>
  </g>
  <g transform="translate(1004 434) scale(0.4286)">${LOGO_MARK}</g>
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

const WEBSITE_LD = {
  '@context': 'https://schema.org',
  '@type': 'WebSite',
  '@id': `${SITE.url}#site`,
  name: SITE.title,
  url: SITE.url,
  description: 'Portable Agent Skills, MCP servers and plugins for AI coding agents.',
  inLanguage: 'en',
  publisher: { '@id': `${SITE.url}#org` },
};

const FAQ_LD = {
  '@context': 'https://schema.org',
  '@type': 'FAQPage',
  mainEntity: FAQ.map((f) => ({
    '@type': 'Question',
    name: f.q,
    acceptedAnswer: { '@type': 'Answer', text: f.a.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim() },
  })),
};

const skillLd = (s) => ({
  '@context': 'https://schema.org',
  '@type': 'SoftwareApplication',
  name: s.name,
  description: s.summary,
  url: `${SITE.url}/s/${s.name}/`,
  applicationCategory: 'DeveloperApplication',
  operatingSystem: 'macOS, Linux, Windows',
  softwareVersion: s.version,
  license: 'https://opensource.org/licenses/MIT',
  isAccessibleForFree: true,
  offers: { '@type': 'Offer', price: '0', priceCurrency: 'USD' },
  author: { '@id': `${SITE.url}#org` },
  codeRepository: s.source,
  softwareRequirements: s.deps.join(', ') || undefined,
});

write('index.html', page({
  title: `${SITE.title} — ${SITE.tagline}`,
  desc: `Portable agent skills for AI coding agents. One SKILL.md folder runs in Claude Code, Codex, Cursor, Gemini CLI, Copilot and ${agentData.ecosystem.approx} more. Open standard, MIT licensed.`,
  active: '/', body: home(), cls: 'p-home', path: '/', jsonld: [WEBSITE_LD, FAQ_LD],
}));

write('browse/index.html', page({
  title: `Browse the catalog — ${SITE.title}`,
  desc: `${catalog.length} portable skills, MCP servers and plugins for AI coding agents. Free and MIT licensed.`,
  active: '/browse/', body: browse(), cls: 'p-browse', og: '/og-browse.png', path: '/browse/',
}));

write('agents/index.html', page({
  title: `Where each AI agent looks for skills — ${SITE.title}`,
  desc: `Verified skill discovery paths for ${agentData.agents.length} AI coding agents, read from each vendor's own documentation, plus ${agentData.compatible.length} more compatible tools.`,
  active: '/agents/', body: agentsPage(), cls: 'p-agents', og: '/og-agents.png', path: '/agents/',
}));

for (const s of skills) {
  write(`s/${s.name}/index.html`, page({
    title: `${s.name} — ${SITE.title}`,
    desc: s.summary,
    active: '/browse/', body: skillPage(s), cls: 'p-skill',
    og: `/og-${s.name}.png`, path: `/s/${s.name}/`, jsonld: [skillLd(s)],
  }));
  write(`og-${s.name}.svg`, ogSvg({ kicker: 'SKILL', title: s.name, sub: s.summary }));
}

write('og.svg', ogSvg({ kicker: 'ITQAN LAB', title: 'Agent Toolkit', sub: SITE.tagline }));
write('og-browse.svg', ogSvg({ kicker: 'CATALOG', title: 'Browse', sub: `${catalog.length} tools for AI coding agents` }));
write('og-agents.svg', ogSvg({ kicker: 'COMPATIBILITY', title: 'Eight agents', sub: 'Verified discovery paths' }));

write('CNAME', `${SITE.domain}\n`);
write('.nojekyll', '');

// AI search engines are a first-class audience here: the whole point of the
// project is being found by people asking an assistant how to do this.
write('robots.txt', `User-agent: *
Allow: /

# AI search crawlers — explicitly welcome
User-agent: GPTBot
Allow: /
User-agent: OAI-SearchBot
Allow: /
User-agent: ChatGPT-User
Allow: /
User-agent: ClaudeBot
Allow: /
User-agent: Claude-User
Allow: /
User-agent: Claude-SearchBot
Allow: /
User-agent: PerplexityBot
Allow: /
User-agent: Perplexity-User
Allow: /
User-agent: Google-Extended
Allow: /
User-agent: Applebot-Extended
Allow: /
User-agent: cohere-ai
Allow: /

Sitemap: ${SITE.url}/sitemap.xml
`);

const today = agentData.verified;
write('sitemap.xml', `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${[['/', '1.0'], ['/browse/', '0.9'], ['/agents/', '0.9'], ...skills.map((s) => [`/s/${s.name}/`, '0.8'])]
    .map(([u, pr]) => `  <url><loc>${SITE.url}${u}</loc><lastmod>${today}</lastmod><priority>${pr}</priority></url>`).join('\n')}
</urlset>`);

// llms.txt — the emerging convention for handing an AI assistant a clean map of
// the site plus the facts it is most likely to be asked for.
write('llms.txt', `# ${SITE.title}

> Portable Agent Skills, MCP servers and Claude Code plugins for AI coding agents.
> One SKILL.md folder runs unchanged in every tool that implements the Agent Skills
> open standard. Free, MIT licensed, no account and no telemetry.
> Made by Itqan Lab (${ORG_LD.url}), a design and technology studio.

## What this is

- An agent skill is a folder containing a SKILL.md file: YAML frontmatter with a name and
  description, Markdown instructions, and optional scripts/, references/ and assets/ directories.
- Agents load the name and description at startup and the full instructions only when a task
  matches, so many skills cost almost no context until used.
- The format is the Agent Skills specification, an open standard stewarded by the Agentic AI
  Foundation: https://agentskills.io/specification

## Pages

- [Overview](${SITE.url}/): What agent skills are, the catalog, and how to install.
- [Browse](${SITE.url}/browse/): All ${catalog.length} skills, MCP servers and plugins, searchable.
- [Agents](${SITE.url}/agents/): Verified skill discovery paths per agent, with vendor sources.
${skills.map((s) => `- [${s.name}](${SITE.url}/s/${s.name}/): ${s.summary}`).join('\n')}

## Install

- Any conformant agent: clone ${SITE.repo} and run ./scripts/install.sh
  This writes to ~/.agents/skills/, the vendor-neutral path.
- Claude Code: /plugin marketplace add itqanlab/agent-toolkit
  then /plugin install <skill>@${SITE.marketplace}

## Key facts

- Verified on ${agentData.verified}: of ${agentData.agents.length} agents whose vendor documentation
  was read directly, ${agentData.agents.filter((a) => a.neutral).length} read ~/.agents/skills/.
- Claude Code is the exception. It reads ~/.claude/skills/, .claude/skills/ and installed plugins
  only, so it installs from a plugin marketplace instead.
- A further ${agentData.ecosystem.approx} tools implement the same standard, including
  ${agentData.compatible.slice(0, 6).map((c) => c.name).join(', ')}.
- Skills stay portable by referencing bundled files with paths relative to the skill root and by
  keeping vendor-specific syntax out of the instruction body.
- Everything is MIT licensed and free for commercial use.

## Source

- Repository: ${SITE.repo}
- Specification: https://agentskills.io/specification
- Full compatibility matrix with sources: ${SITE.repo}/blob/main/docs/COMPATIBILITY.md
`);

cpSync(join(HERE, 'static'), OUT, { recursive: true });

console.log(`built → site/dist`);
console.log(`  pages   ${3 + skills.length}`);
console.log(`  catalog ${catalog.length} (${counts.skill} skill · ${counts.mcp} mcp · ${counts.plugin} plugin)`);
console.log(`  agents  ${agentData.agents.length}`);
