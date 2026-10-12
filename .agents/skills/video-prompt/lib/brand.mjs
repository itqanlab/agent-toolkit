// brand.mjs — read the host project's brand file and log the prompts written from it.
//
// Shared by image-prompt and video-prompt. Each plugin keeps its own identical copy, so a
// skill folder copied on its own still works. Node standard library only.
//
// The brand file is plain Markdown that the project owns. Nothing about any brand is written
// here: every style value comes from that file at run time, and the prompt says nothing about
// a brand when there is no file.

import { existsSync, readFileSync, mkdirSync, appendFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { createHash } from 'node:crypto';

// Looked for in this order in the folder the command runs from, after --brand and BRAND_FILE.
export const BRAND_FILES = ['brand.md', 'BRAND.md', 'brand/brand.md', 'docs/brand.md'];

// Each section is found by its `## ` heading. Any of these words in the heading matches.
const SECTIONS = {
  name: /^(name|brand|label)\b/i,
  // Before `look`, so "Studio photography" lands here: rules for product shots only.
  studio: /studio|product shots?|catalog/i,
  palette: /palette|colou?rs?/i,
  look: /photo|visual|look|imagery|style/i,
  motion: /motion|movement|camera|video/i,
  tone: /tone|voice|mood|personality/i,
  avoid: /don'?t|avoid|never|not to/i,
};

/** Find the brand file. Returns null when the project has none, which is fine. */
export function findBrand(explicit) {
  if (explicit) {
    const p = resolve(explicit);
    if (!existsSync(p)) throw new Error(`no brand file at ${p}`);
    return p;
  }
  if (process.env.BRAND_FILE) {
    const p = resolve(process.env.BRAND_FILE);
    if (existsSync(p)) return p;
  }
  for (const f of BRAND_FILES) {
    const p = resolve(f);
    if (existsSync(p)) return p;
  }
  return null;
}

/** Split the file into the sections the prompt uses. Lines become short clauses. */
export function readBrand(file) {
  const out = { file, name: null, studio: [], palette: [], look: [], motion: [], tone: [], avoid: [], found: [] };
  const text = readFileSync(file, 'utf8').replace(/\r\n?/g, '\n');
  const h1 = /^#\s+(.+)$/m.exec(text);
  if (h1) out.name = h1[1].trim();
  let current = null;
  for (const raw of text.split('\n')) {
    const h = /^##\s+(.+)$/.exec(raw);
    if (h) {
      current = Object.keys(SECTIONS).find((k) => SECTIONS[k].test(h[1].trim())) || null;
      if (current && !out.found.includes(current)) out.found.push(current);
      continue;
    }
    if (!current) continue;
    const line = raw.replace(/^\s*([-*+]|\d+\.)\s+/, '').replace(/\*\*/g, '').trim();
    if (!line || line.startsWith('<!--') || line.startsWith('#')) continue;
    if (current === 'name') { out.name = line; continue; }
    out[current].push(line.replace(/[.;]+$/, ''));
  }
  return out;
}

const clause = (items) => items.join('. ');

/**
 * The style lines a prompt carries, by mode.
 *   full     look (plus studio rules on studio shots), palette, tone, motion (video)
 *   minimal  look (plus studio rules on studio shots) only
 * The don't list is added by the caller in every mode but none.
 *   none     nothing from the brand
 */
export function styleBlock(brand, mode, { video = false, studio = false } = {}) {
  if (!brand || mode === 'none') return {};
  const block = {};
  const look = [...brand.look, ...(studio ? brand.studio : [])];
  if (look.length) block.STYLE = clause(look);
  if (mode === 'full') {
    if (brand.palette.length) block.PALETTE = clause(brand.palette);
    if (brand.tone.length) block.MOOD = clause(brand.tone);
    if (video && brand.motion.length) block.MOTION = clause(brand.motion);
  }
  return block;
}

// ------------------------------------------------------------------ the prompt log

export const home = () => resolve(process.env.PROMPTS_HOME || join(process.cwd(), '.prompts'));
const logPath = () => join(home(), 'log.jsonl');
export const hash = (o) => createHash('sha256').update(JSON.stringify(o)).digest('hex').slice(0, 12);

const words = (s) => new Set(String(s).toLowerCase().match(/[a-z0-9؀-ۿ]{3,}/g) || []);

/**
 * Prompts already written in this project that look like this one: the exact same request,
 * or one for the same platform in the last 30 days whose words overlap by 60% or more.
 */
export function similar({ id, kind, platform, subject }) {
  if (!existsSync(logPath())) return [];
  const mine = words(subject);
  const since = Date.now() - 30 * 86400000;
  const rows = readFileSync(logPath(), 'utf8').trim().split('\n').filter(Boolean).map((l) => JSON.parse(l));
  return rows.filter((r) => {
    if (r.kind !== kind) return false;
    if (r.id === id) return true;
    if (r.platform !== platform || Date.parse(r.at) < since || !mine.size) return false;
    const theirs = words(r.subject);
    let shared = 0;
    for (const w of mine) if (theirs.has(w)) shared += 1;
    return shared / mine.size >= 0.6;
  });
}

export function log(row) {
  mkdirSync(home(), { recursive: true });
  appendFileSync(logPath(), `${JSON.stringify({ at: new Date().toISOString(), ...row })}\n`);
}

export function parseArgs(argv) {
  const out = { _: [] };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (!a.startsWith('--')) { out._.push(a); continue; }
    const k = a.slice(2);
    const v = argv[i + 1];
    if (v === undefined || v.startsWith('--')) out[k] = true;
    else { out[k] = v; i += 1; }
  }
  return out;
}

const gcd = (a, b) => (b ? gcd(b, a % b) : a);
// 1080x1350 is 4:5. 1200x630 reduces to 40:21, which nobody says, so it reads 1.91:1.
export const ratioOf = (w, h) => {
  const a = w / gcd(w, h);
  const b = h / gcd(w, h);
  return a <= 21 && b <= 21 ? `${a}:${b}` : `${(w / h).toFixed(2).replace(/0$/, '')}:1`;
};

/** Higgsfield's models take a few ratios; pick the nearest one it is likely to accept. */
export function nearestRatio(w, h) {
  const options = ['1:1', '4:5', '3:4', '2:3', '9:16', '16:9', '4:3', '3:2', '21:9'];
  const target = w / h;
  return options.reduce((best, r) => {
    const [a, b] = r.split(':').map(Number);
    return Math.abs(a / b - target) < Math.abs(best[0] - target) ? [a / b, r] : best;
  }, [Infinity, '1:1'])[1];
}
