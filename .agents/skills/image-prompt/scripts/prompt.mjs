#!/usr/bin/env node
// prompt.mjs — write an image prompt, in the project's brand, sized for the platform.
//
// It writes text. It never calls an image service. The result is prompt.txt (the prompt alone,
// ready to copy) and prompt.json (the prompt plus size, ratio, don't list and a suggested
// Higgsfield model), and with --paste a short PASTE.md for a web tool.

import { writeFileSync, mkdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { findBrand, readBrand, styleBlock, similar, log, hash, parseArgs, ratioOf, nearestRatio, home } from '../lib/brand.mjs';

// Pixel sizes each platform documents for its own uploads.
export const SIZES = {
  product_page: { default: [2048, 2048] },
  instagram_post: { square: [1080, 1080], portrait: [1080, 1350], landscape: [1080, 566], default: [1080, 1350] },
  instagram_story: { default: [1080, 1920] },
  instagram_reel_cover: { default: [1080, 1920] },
  facebook_post: { landscape: [1200, 630], square: [1080, 1080], default: [1080, 1080] },
  facebook_story: { default: [1080, 1920] },
  linkedin_post: { landscape: [1200, 627], square: [1200, 1200], default: [1200, 1200] },
  x_post: { default: [1600, 900] },
  pinterest_pin: { default: [1000, 1500] },
  youtube_thumbnail: { default: [1280, 720] },
};

// The four directions, so a feed does not look the same post after post.
export const TYPES = {
  editorial: {
    use: 'feed and story posts that must stop the scroll',
    subject: (s) => `An editorial photograph built around ${s}. The subject is the hero: fully visible, in sharp focus, read first.`,
    scene: 'A real, evocative location that complements the palette. Cinematic natural light.',
    camera: 'Photorealistic, shot on medium format, shallow depth of field.',
    avoid: ['text or lettering in the image', 'watermarks', 'second copy of the subject', 'clutter', 'over-retouched or artificial look'],
    model: 'gpt_image_2_5',
    people: 'text2image_soul_v2',
  },
  'clean-studio': {
    use: 'product pages, catalogs and plain product posts',
    subject: (s) => `A clean studio product photograph of ${s}.`,
    scene: 'Seamless plain background. Soft directional light from the upper left. Subject centred with room around it.',
    camera: 'Eye level, sharp focus, a single subject.',
    avoid: ['people or hands', 'props', 'text', 'watermarks', 'hard dramatic shadows'],
    model: 'gpt_image_2_5',
  },
  detail: {
    use: 'story inserts and variety in a feed',
    subject: (s) => `An extreme close-up of ${s}: the material, texture, stitching or hardware. The whole object is not shown.`,
    scene: 'Raking light that brings out the texture. Quiet, uncluttered background.',
    camera: 'Macro lens, very shallow depth of field.',
    avoid: ['full view of the object', 'text', 'watermarks', 'busy backgrounds'],
    model: 'gpt_image_2_5',
  },
  'branded-overlay': {
    use: 'announcements and posts that carry a short line of text',
    subject: (s) => `A product image of ${s} with clear empty space for a short headline.`,
    scene: 'Calm background with one area left empty for text, away from the subject.',
    camera: 'Subject placed off centre, toward the side opposite the text area.',
    avoid: ['text over the subject', 'more than one line of headline', 'watermarks'],
    model: 'gpt_image_2_5',
  },
};

const USAGE = `prompt.mjs — write an image prompt in the project's brand, sized for the platform.

  node scripts/prompt.mjs --subject "..." [--type editorial] [--platform instagram_post] [--variant portrait]
       [--size 1080x1350] [--reference] [--people] [--headline "..."] [--scene "..."]
       [--brand FILE] [--brand-mode full|minimal|none] [--paste "Tool name"] [--out DIR] [--force]
  node scripts/prompt.mjs sizes        every platform, variant and pixel size
  node scripts/prompt.mjs brand        which brand file is used and what was read from it

Types: ${Object.keys(TYPES).join(', ')}
Brand file: --brand, else BRAND_FILE, else brand.md, BRAND.md, brand/brand.md or docs/brand.md here.`;

function size(A) {
  if (typeof A.size === 'string') {
    const m = /^(\d+)x(\d+)$/.exec(A.size);
    if (!m) throw new Error('--size must look like 1080x1350');
    return { platform: 'custom', variant: null, w: Number(m[1]), h: Number(m[2]) };
  }
  const platform = typeof A.platform === 'string' ? A.platform : 'instagram_post';
  const p = SIZES[platform];
  if (!p) throw new Error(`unknown platform "${platform}". See: node scripts/prompt.mjs sizes`);
  const variant = typeof A.variant === 'string' ? A.variant : 'default';
  if (!p[variant]) throw new Error(`${platform} has no "${variant}" variant. It has: ${Object.keys(p).join(', ')}`);
  return { platform, variant: variant === 'default' ? null : variant, w: p[variant][0], h: p[variant][1] };
}

export function build(A) {
  if (!A.subject || A.subject === true) throw new Error('--subject is needed: what the image shows');
  const type = typeof A.type === 'string' ? A.type : 'editorial';
  const t = TYPES[type];
  if (!t) throw new Error(`unknown type "${type}". Types: ${Object.keys(TYPES).join(', ')}`);
  const mode = typeof A['brand-mode'] === 'string' ? A['brand-mode'] : 'full';
  if (!['full', 'minimal', 'none'].includes(mode)) throw new Error('--brand-mode is full, minimal or none');
  const brandFile = mode === 'none' ? null : findBrand(typeof A.brand === 'string' ? A.brand : null);
  const brand = brandFile ? readBrand(brandFile) : null;
  const { platform, variant, w, h } = size(A);
  const ratio = ratioOf(w, h);
  const orient = w === h ? 'square' : w > h ? 'horizontal' : 'vertical';

  // A headline the user asked for wins over a brand rule against text in images.
  const headline = type === 'branded-overlay' && typeof A.headline === 'string';
  const lines = [];
  // Image models tend to hand a reference back unchanged unless told to build a new scene.
  if (A.reference) lines.push('Use the attached image as the exact reference for the subject: keep its shape, materials, colours and details. Build a new scene around it as described. Do not return the reference unchanged.');
  lines.push(`[SUBJECT] ${t.subject(A.subject)}`);
  if (A.people) lines.push('[PEOPLE] A person styled with the subject. The subject stays the hero and reads first; the face may be partly framed out.');
  lines.push(`[SCENE] ${typeof A.scene === 'string' ? A.scene : t.scene}`);
  const studio = type === 'clean-studio' || type === 'detail';
  for (const [k, v] of Object.entries(styleBlock(brand, mode, { studio }))) lines.push(`[${k}] ${v}`);
  if (headline) lines.push(`[TEXT] Render this headline once, large and legible, in the empty area: "${A.headline}"`);
  lines.push(`[CAMERA] ${t.camera} ${orient[0].toUpperCase() + orient.slice(1)} ${ratio} frame.`);
  // Our own items are nouns and get "No". The brand's lines are kept as the brand wrote them.
  const brandAvoid = (brand && mode !== 'none' ? brand.avoid : []).filter((a) => !(headline && /\btext\b/i.test(a)));
  // The same rule from the shot and the brand is said once.
  const avoid = [...new Map([...t.avoid.map((a) => `No ${a}`), ...brandAvoid.map((a) => a[0].toUpperCase() + a.slice(1))]
    .map((a) => [a.toLowerCase().replace(/[^a-z0-9 ]/g, ''), a])).values()];
  lines.push(`[AVOID] ${avoid.join('. ')}.`);
  lines.push(`Render as a ${ratio} ${orient} image, ${w}x${h}, photorealistic.`);
  const prompt = lines.join('\n');

  const model = A.reference ? 'nano_banana_2_lite' : A.people && t.people ? t.people : t.model;
  const higgsRatio = nearestRatio(w, h);
  return {
    kind: 'image',
    subject: A.subject,
    type,
    platform,
    variant,
    width: w,
    height: h,
    aspect_ratio: ratio,
    prompt,
    avoid,
    reference: Boolean(A.reference),
    brand: brand ? { file: brand.file, mode, sections: brand.found } : { file: null, mode: brandFile === null && mode !== 'none' ? 'none (no brand file found)' : mode },
    higgsfield: {
      model,
      aspect_ratio: higgsRatio,
      crop_to: higgsRatio === ratio ? null : `${w}x${h}`,
      how: 'Give prompt.txt to the higgsfield-studio skill: its create command with --prompt-file, this model and --aspect_ratio, plus --image for the reference. It quotes the price before anything is spent. Check the model parameters with its run model get first.',
    },
  };
}

function pastePack(result, tool) {
  return `# ${tool}: ${result.subject}

Web tools change their screens often. These steps are kept general on purpose.

1. Open ${tool} and start a new image.
2. ${result.reference ? 'Attach the reference image before sending.' : 'No reference image is needed.'}
3. If it has an aspect ratio setting, choose ${result.higgsfield.aspect_ratio}. If not, the prompt already asks for ${result.aspect_ratio}.
4. Paste the whole of prompt.txt from this folder and send it.
5. If text, watermarks or a changed subject appear, ask it to remove them and keep the rest.
6. Download the image${result.higgsfield.crop_to ? `, then crop it to ${result.higgsfield.crop_to}` : ''}.

Don't list: ${result.avoid.join('; ')}.
`;
}

const COMMANDS = {
  help() { console.log(USAGE); },
  sizes() {
    for (const [p, v] of Object.entries(SIZES)) {
      for (const [k, [w, h]] of Object.entries(v)) console.log(`${p.padEnd(22)} ${k.padEnd(10)} ${String(w).padStart(5)}x${h}  ${ratioOf(w, h)}`);
    }
  },
  brand(A) {
    const f = findBrand(typeof A.brand === 'string' ? A.brand : null);
    if (!f) { console.log('no brand file found. Prompts carry no brand style until one exists (see references/brand-file.md).'); return; }
    const b = readBrand(f);
    console.log(`brand file: ${f}`);
    console.log(`name: ${b.name || '(none)'}   sections read: ${b.found.join(', ') || 'none'}`);
    for (const k of ['palette', 'look', 'studio', 'tone', 'avoid']) console.log(`  ${k.padEnd(8)} ${b[k].length} line(s)`);
  },
  write(A) {
    const r = build(A);
    const id = hash({ kind: r.kind, subject: r.subject, type: r.type, platform: r.platform, variant: r.variant, w: r.width, h: r.height, prompt: r.prompt });
    const seen = similar({ id, kind: 'image', platform: r.platform, subject: r.subject });
    if (seen.length && !A.force) {
      console.log('A similar prompt was already written in this project:');
      for (const s of seen.slice(-3)) console.log(`  ${s.at.slice(0, 10)}  ${s.type}  "${s.subject}"  -> ${s.out}`);
      console.log('Reuse it, or run again with --force to write a new one.');
      process.exitCode = 3;
      return;
    }
    const out = resolve(typeof A.out === 'string' ? A.out : join(home(), `${new Date().toISOString().slice(0, 10)}-image-${id}`));
    mkdirSync(out, { recursive: true });
    writeFileSync(join(out, 'prompt.txt'), `${r.prompt}\n`);
    writeFileSync(join(out, 'prompt.json'), `${JSON.stringify({ id, ...r }, null, 2)}\n`);
    if (typeof A.paste === 'string') writeFileSync(join(out, 'PASTE.md'), pastePack(r, A.paste));
    log({ id, kind: 'image', type: r.type, platform: r.platform, subject: r.subject, out });
    console.log(r.prompt);
    console.log(`\n${r.width}x${r.height} (${r.aspect_ratio})   brand: ${r.brand.file || r.brand.mode}   suggested Higgsfield model: ${r.higgsfield.model} at ${r.higgsfield.aspect_ratio}${r.higgsfield.crop_to ? `, then crop to ${r.higgsfield.crop_to}` : ''}`);
    console.log(`written: ${out}`);
  },
};

const isMain = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
if (isMain) {
  const A = parseArgs(process.argv.slice(2));
  const cmd = A._[0] || (A.subject ? 'write' : 'help');
  const handler = COMMANDS[A.help ? 'help' : cmd];
  if (!handler) { console.error(`unknown command "${cmd}"\n\n${USAGE}`); process.exit(1); }
  try { handler(A); } catch (err) { console.error(err.message); process.exit(1); }
}
