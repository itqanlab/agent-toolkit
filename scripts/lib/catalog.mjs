// Shared readers for the skill folders. Used by the catalog generator and the
// site build, so both parse a skill the same way.

import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { join } from 'node:path';

const unquote = (v) => v.replace(/^["']|["']$/g, '').trim();

// Minimal frontmatter reader. The spec allows only scalars and a flat metadata
// map, so a full YAML parser would be more surface than the format needs.
export function frontmatter(src) {
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

// Triggers are written into the description as: Triggers: 'a', 'b', 'c'.
// The separator is matched loosely. A skill that writes "Triggers," instead of
// "Triggers:" is following the convention in spirit, and silently dropping its
// whole trigger list is worse than accepting a comma. validate.sh warns when the
// canonical form is not used.
export function splitDescription(desc = '') {
  const i = desc.search(/Triggers?\s*[:,—-]/i);
  if (i === -1) return { summary: desc.trim(), triggers: [] };
  const summary = desc.slice(0, i).trim();
  const triggers = [...desc.slice(i).matchAll(/'([^']+)'/g)].map((m) => m[1]);
  return { summary, triggers };
}

// "Requires ffmpeg, and yt-dlp for URL sources." -> ['ffmpeg', 'yt-dlp']
// "Git Bash" is the Windows fallback for a bash script, not a dependency on git.
export function deps(compat = '') {
  const found = new Set();
  for (const m of compat.matchAll(/\b(ffmpeg|yt-dlp|python|node|uv|git(?!\s+bash)|docker|jq|pandoc|imagemagick)\b/gi)) {
    found.add(m[1].toLowerCase());
  }
  return [...found];
}

// Every folder under skills/ that holds a SKILL.md, sorted by name.
export function readSkills(root) {
  const dir = join(root, 'skills');
  if (!existsSync(dir)) return [];
  return readdirSync(dir, { withFileTypes: true })
    .filter((e) => e.isDirectory() && existsSync(join(dir, e.name, 'SKILL.md')))
    .map((e) => {
      const base = join(dir, e.name);
      const { data } = frontmatter(readFileSync(join(base, 'SKILL.md'), 'utf8'));
      const pluginPath = join(base, '.claude-plugin', 'plugin.json');
      return {
        name: e.name,
        base,
        fm: data,
        plugin: existsSync(pluginPath) ? JSON.parse(readFileSync(pluginPath, 'utf8')) : null,
      };
    })
    .sort((a, b) => a.name.localeCompare(b.name));
}
