// Shared icon renderer. Used by scripts/build-icons.mjs (writes the files) and by
// site/build.mjs (draws a still icon into each share card), so both draw the same thing.
//
// The look is "B2 Hairline": a thin line, two fading echoes of the outline for depth, a faint
// tint inside, one amber accent, tiny ring "records", and the small Itqan mark in a corner.
//
// A tool is described by plugins/<name>/assets/glyph.svg: shapes only, on a 512 canvas,
// centred, no colours. Each shape says what it is with a class:
//
//   main         outline. It gets the two echoes. A path.
//   main tint    the same, and the inside gets the faint tint.
//   tint         only the tint, no line.
//   line         a thin line in the main colour. A path.
//   acc          a thin line in amber. A path.
//   ring         a circle outline, main colour.   ring-acc  the same in amber.
//   dot          a filled circle, main colour.    dot-acc   the same in amber.
//
// An optional single <g transform="..."> around everything moves the whole drawing.
// main, line and acc must be <path>: the draw-on motion uses pathLength, which browsers
// only honour on paths.

import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const read = (p) => readFileSync(p, 'utf8').replace(/\r\n?/g, '\n');

const THEMES = {
  dark: {
    t0: '#1a1a1f', t1: '#09090B', edge: '#d4a853', edgeO: '.2',
    pri: '#d4a853', acc: '#f59e0b', echo: '#d97706', echoO: ['.45', '.25'],
    tint: '#d4a853', tintO: '.065', glow: '#d97706', glowO: '.22',
    chip: '#0f0f11', chipEdge: '#d4a853',
  },
  light: {
    t0: '#ffffff', t1: '#ebe8e0', edge: '#09090B', edgeO: '.1',
    pri: '#9a6a12', acc: '#d97706', echo: '#d97706', echoO: ['.42', '.23'],
    tint: '#d97706', tintO: '.05', glow: '#d97706', glowO: '.13',
    chip: '#09090B', chipEdge: '#d4a853',
  },
};

// Line weights on the 512 canvas. Hairline is too thin below about 40px, so the small icon
// (used at 32px and under, and for the composer) draws the same shapes heavier.
const WEIGHTS = {
  full: { main: 5, line: 4, acc: 4.5, ring: 4, echo: [4, 3] },
  small: { main: 10, line: 8, acc: 8, ring: 8, echo: [7] },
};
const ECHO_OFFSETS = [[12, 10], [24, 20]];

// The Itqan logo as in site/static/logo.svg, minus the outer <svg> and its tile.
const logoInner = (() => {
  const s = read(join(ROOT, 'site', 'static', 'logo.svg'));
  return s.slice(s.indexOf('>') + 1, s.lastIndexOf('</svg>'))
    .replace('<rect width="280" height="280" rx="56" fill="#09090B"/>', '');
})();

export function readGlyph(pluginDir) {
  const src = read(join(pluginDir, 'assets', 'glyph.svg')).replace(/<!--[\s\S]*?-->/g, '');
  const inner = src.slice(src.indexOf('>', src.indexOf('<svg')) + 1, src.lastIndexOf('</svg>'));
  const wrap = inner.match(/<g\b[^>]*\btransform="([^"]*)"/);
  const shapes = [];
  for (const m of inner.matchAll(/<(path|circle|ellipse)\b([^>]*?)\/?>/g)) {
    const attrs = m[2];
    const cls = (attrs.match(/\bclass="([^"]*)"/) || [, ''])[1].split(/\s+/).filter(Boolean);
    const geom = attrs.replace(/\bclass="[^"]*"/, '').trim();
    if (!cls.length) throw new Error(`glyph shape without a class: <${m[1]} ${attrs.trim()}>`);
    if (['main', 'line', 'acc'].some((k) => cls.includes(k)) && m[1] !== 'path') {
      throw new Error(`glyph: ${cls.join(' ')} must be a <path>, not <${m[1]}>`);
    }
    shapes.push({ tag: m[1], geom, cls });
  }
  if (!shapes.length) throw new Error(`no shapes in ${pluginDir}/assets/glyph.svg`);
  return { transform: wrap ? wrap[1] : '', shapes };
}

const el = (s, cls, extra = '') => `<${s.tag} ${s.geom}${cls ? ` class="${cls}"` : ''}${extra}/>`;

function css(c, w, motion) {
  const base = `
.main,.line,.acc,.ring,.ring-acc,.ec{fill:none;stroke-linecap:round;stroke-linejoin:round}
.main,.line,.ring{stroke:${c.pri}}.acc,.ring-acc{stroke:${c.acc}}
.main{stroke-width:${w.main}}.line{stroke-width:${w.line}}.acc{stroke-width:${w.acc}}.ring,.ring-acc{stroke-width:${w.ring}}
.dot{fill:${c.pri}}.dot-acc{fill:${c.acc}}.dot,.dot-acc{stroke:none}
.fill{fill:${c.tint};fill-opacity:${c.tintO};stroke:none}
.ec{stroke:${c.echo}}.e0 .ec{stroke-width:${w.echo[0]}}.e1 .ec{stroke-width:${w.echo[1] || 0}}`;
  if (!motion) return base;
  // Every animation starts from the drawn pose or ends on it, so a still export equals the
  // finished frame. The whole block is skipped for people who ask for reduced motion.
  return `${base}
@media (prefers-reduced-motion:no-preference){
.main,.line,.acc{stroke-dasharray:1;animation:draw 1.6s cubic-bezier(.6,0,.2,1) both}
.line,.acc{animation-delay:1.1s}
.node{transform-box:fill-box;transform-origin:center;animation:pop .6s cubic-bezier(.3,1.6,.5,1) both;animation-delay:calc(1.9s + var(--i)*.15s)}
.echo{animation:drift 5s ease-in-out infinite}.e1 .echo{animation-delay:.4s}
@keyframes draw{from{stroke-dashoffset:1}to{stroke-dashoffset:0}}
@keyframes pop{from{transform:scale(0);opacity:0}to{transform:scale(1);opacity:1}}
@keyframes drift{50%{transform:translate(8px,6px)}}}`;
}

/**
 * @param glyph  from readGlyph()
 * @param opts   theme 'dark'|'light', size 'full'|'small', motion boolean
 */
export function renderIcon(glyph, { theme = 'dark', size = 'full', motion = false } = {}) {
  const c = THEMES[theme];
  const w = WEIGHTS[size];
  const mains = glyph.shapes.filter((s) => s.cls.includes('main'));
  const echoes = ECHO_OFFSETS.slice(0, w.echo.length).map(([dx, dy], i) =>
    `<g transform="translate(${dx} ${dy})" opacity="${c.echoO[i]}"><g class="e${i}"><g class="echo">${
      mains.map((s) => el(s, 'ec')).join('')}</g></g></g>`).join('');
  const tint = glyph.shapes.filter((s) => s.cls.includes('tint')).map((s) => el(s, 'fill')).join('');

  // Records that share a centre pop together and take their turn in order of first sight.
  const order = new Map();
  const idx = (s) => {
    const key = (s.geom.match(/cx="([^"]*)"/) || [])[1] + ',' + (s.geom.match(/cy="([^"]*)"/) || [])[1];
    if (!order.has(key)) order.set(key, order.size);
    return order.get(key);
  };
  const body = glyph.shapes.map((s) => {
    const k = s.cls.find((x) => ['main', 'line', 'acc', 'ring', 'ring-acc', 'dot', 'dot-acc'].includes(x));
    if (!k) return '';
    if (k === 'main' || k === 'line' || k === 'acc') return el(s, k, ' pathLength="1"');
    return `<g class="node" style="--i:${idx(s)}">${el(s, k)}</g>`;
  }).join('\n    ');

  const place = size === 'small'
    ? 'translate(256 256) scale(1.14) translate(-256 -256)'
    : 'translate(-27 -8)';
  const chip = size === 'full' ? `
  <g id="itqan-mark" transform="translate(350 350) scale(0.3714)">
    <rect width="280" height="280" rx="56" fill="${c.chip}" stroke="${c.chipEdge}" stroke-width="8"/>${logoInner}
  </g>` : '';

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">
  <defs>
    <linearGradient id="t" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${c.t0}"/><stop offset="1" stop-color="${c.t1}"/></linearGradient>
    <radialGradient id="g" cx=".5" cy=".42" r=".5"><stop offset="0" stop-color="${c.glow}" stop-opacity="${c.glowO}"/><stop offset="1" stop-color="${c.glow}" stop-opacity="0"/></radialGradient>
  </defs>
  <style>${css(c, w, motion)}
  </style>
  <g id="tile"><rect width="512" height="512" rx="112" fill="url(#t)"/><rect x="1.5" y="1.5" width="509" height="509" rx="110.5" fill="none" stroke="${c.edge}" stroke-opacity="${c.edgeO}" stroke-width="3"/></g>
  <circle id="glow" cx="236" cy="230" r="210" fill="url(#g)"/>
  <g id="drawing" transform="${place}">
   <g${glyph.transform ? ` transform="${glyph.transform}"` : ''}>
    <g id="echo">${echoes}</g>
    <g id="tint">${tint}</g>
    ${body}
   </g>
  </g>${chip}
</svg>
`;
}
