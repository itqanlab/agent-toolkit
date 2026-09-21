#!/usr/bin/env node
// build-icons.mjs — draw each tool's icon from one small drawing.
//
// A tool owns one file: plugins/<name>/assets/glyph.svg. It is only the shapes (the
// vocabulary is at the top of scripts/lib/icons.mjs). This script draws the tile, the
// echoes, the tint and the small Itqan mark, and writes every size an agent app asks for.
//
//   plugins/<name>/assets/icon-dark.svg, icon-light.svg           layered, animated (site, docs)
//   plugins/<name>/assets/icon-small-dark.svg, icon-small-light.svg   still, heavier line, no Itqan mark
//   plugins/<name>/assets/logo.png             512, light   Codex plugin card `interface.logo`
//   plugins/<name>/assets/logo-dark.png        512, dark    Codex `interface.logoDark`
//   plugins/<name>/assets/composer-icon.png    128, dark    Codex `interface.composerIcon`
//   plugins/<name>/skills/<name>/assets/icon-large.png   512  Codex openai.yaml icon_large
//   plugins/<name>/skills/<name>/assets/icon-small.png   128  Codex openai.yaml icon_small
//
// The skill copies exist because a skill installed alone (npx skills, ~/.agents/skills)
// carries only its own folder, and Codex rejects a path that leaves it.
//
//   node scripts/build-icons.mjs [name...]     write the icons (all tools by default)
//   node scripts/build-icons.mjs --check       fail if a file is missing or out of date
//
// Writing needs rsvg-convert (librsvg), which the Pages workflow already installs. --check
// does not: it compares the SVGs exactly and only looks for the PNGs, because two librsvg
// versions do not draw the same bytes.

import { readFileSync, writeFileSync, existsSync, readdirSync, mkdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { readGlyph, renderIcon } from './lib/icons.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const PLUGINS = join(ROOT, 'plugins');
const check = process.argv.includes('--check');
const only = process.argv.slice(2).filter((a) => !a.startsWith('--'));

const read = (p) => readFileSync(p, 'utf8').replace(/\r\n?/g, '\n');
const png = (svg, size) => execFileSync('rsvg-convert', ['-w', String(size), '-h', String(size)], { input: svg });

const problems = [];
const label = (p) => p.slice(ROOT.length + 1).split('\\').join('/');
// `make` is only called when a file is really written, so --check never needs rsvg-convert.
const emit = (path, make, isPng) => {
  if (check) {
    const svg = isPng ? null : make();
    if (!existsSync(path) || (svg !== null && read(path) !== svg)) problems.push(label(path));
    return;
  }
  const next = make();
  if (existsSync(path) && (isPng ? readFileSync(path).equals(next) : read(path) === next)) return;
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, next);
  console.log('wrote', label(path));
};

export const iconTools = readdirSync(PLUGINS, { withFileTypes: true })
  .filter((d) => d.isDirectory() && existsSync(join(PLUGINS, d.name, 'assets', 'glyph.svg')))
  .map((d) => d.name);

const names = iconTools.filter((n) => !only.length || only.includes(n));

for (const name of names) {
  const dir = join(PLUGINS, name);
  const glyph = readGlyph(dir);
  const svg = (theme, size, motion) => () => renderIcon(glyph, { theme, size, motion });
  // A png is drawn from the still version, never the animated one.
  const raster = (theme, size, px) => () => png(renderIcon(glyph, { theme, size, motion: false }), px);

  emit(join(dir, 'assets', 'icon-dark.svg'), svg('dark', 'full', true));
  emit(join(dir, 'assets', 'icon-light.svg'), svg('light', 'full', true));
  emit(join(dir, 'assets', 'icon-small-dark.svg'), svg('dark', 'small', false));
  emit(join(dir, 'assets', 'icon-small-light.svg'), svg('light', 'small', false));
  emit(join(dir, 'assets', 'logo.png'), raster('light', 'full', 512), true);
  emit(join(dir, 'assets', 'logo-dark.png'), raster('dark', 'full', 512), true);
  emit(join(dir, 'assets', 'composer-icon.png'), raster('dark', 'small', 128), true);
  const skill = join(dir, 'skills', name, 'assets');
  emit(join(skill, 'icon-large.png'), raster('dark', 'full', 512), true);
  emit(join(skill, 'icon-small.png'), raster('dark', 'small', 128), true);
}

if (check && problems.length) {
  console.error(`icons out of date (run: node scripts/build-icons.mjs):\n  ${problems.join('\n  ')}`);
  process.exit(1);
}
console.log(check ? `icons ok (${names.length} tool${names.length === 1 ? '' : 's'})` : `done (${names.length} tool${names.length === 1 ? '' : 's'})`);
