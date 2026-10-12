#!/usr/bin/env node
// prompt.mjs — write a video prompt, in the project's brand, sized and timed for the platform.
//
// It writes text. It never calls a video service. The result is prompt.txt (the prompt alone,
// ready to copy) and prompt.json (the prompt plus size, ratio, length, don't list and a
// suggested Higgsfield model), and with --paste a short PASTE.md for a web tool.

import { writeFileSync, mkdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { findBrand, readBrand, styleBlock, similar, log, hash, parseArgs, ratioOf, nearestRatio, home } from '../lib/brand.mjs';

// Pixel size, the length range the platform accepts, and a sensible default length in seconds.
export const SIZES = {
  instagram_reel: { default: [1080, 1920, 3, 90, 7] },
  instagram_story: { default: [1080, 1920, 1, 60, 7] },
  instagram_post: { square: [1080, 1080, 3, 60, 7], portrait: [1080, 1350, 3, 60, 7], default: [1080, 1350, 3, 60, 7] },
  facebook_reel: { default: [1080, 1920, 3, 90, 7] },
  facebook_story: { default: [1080, 1920, 1, 20, 7] },
  facebook_feed: { landscape: [1280, 720, 3, 240, 10], square: [1080, 1080, 3, 240, 10], default: [1080, 1080, 3, 240, 10] },
  tiktok: { default: [1080, 1920, 3, 600, 10] },
  youtube_short: { default: [1080, 1920, 3, 60, 10] },
  youtube: { default: [1920, 1080, 3, 3600, 10] },
  linkedin_post: { landscape: [1920, 1080, 3, 600, 10], square: [1080, 1080, 3, 600, 10], default: [1080, 1080, 3, 600, 10] },
  product_page: { default: [1080, 1080, 3, 10, 5] },
};

// Shot types, the video counterpart of the image directions.
export const TYPES = {
  turntable: {
    use: 'product pages and catalog posts',
    subject: (s) => `${s}, alone, centred.`,
    scene: 'Clean studio. Seamless plain background. Soft, diffused directional light.',
    motion: 'A slow, smooth turn of the subject on its axis, or a gentle floating lift. One continuous shot.',
    camera: 'Locked-off camera, shallow depth of field, subject centred throughout.',
    avoid: ['people or hands', 'props', 'text overlays', 'quick cuts', 'shaky camera'],
    studio: true,
  },
  'hero-reveal': {
    use: 'launches, announcements and the first second of a reel',
    subject: (s) => `${s}, revealed as the hero of the shot.`,
    scene: 'A calm, simple setting that complements the palette, with light that builds toward the subject.',
    motion: 'A slow push-in or a reveal from shadow or out of focus into a sharp, well-lit subject. The subject is clear by the halfway point.',
    camera: 'One continuous move, ending on a clean, still frame.',
    avoid: ['text overlays', 'flash effects', 'fast zooms', 'second subject'],
  },
  editorial: {
    use: 'feed reels and stories that must stop the scroll',
    subject: (s) => `A cinematic scene built around ${s}. The subject is the hero and reads first.`,
    scene: 'A real, evocative location. Natural cinematic light.',
    motion: 'Unhurried, natural movement in the scene. The camera follows or drifts slowly.',
    camera: 'Shallow depth of field, the subject in sharp focus, filmic grade.',
    avoid: ['text overlays', 'watermarks', 'quick cuts', 'artificial look'],
  },
  detail: {
    use: 'texture moments and story inserts',
    subject: (s) => `An extreme close-up of ${s}: its material, texture or mechanism.`,
    scene: 'Raking light that brings out the texture. Quiet background.',
    motion: 'A slow, gliding macro move across the surface.',
    camera: 'Macro lens, very shallow depth of field.',
    avoid: ['full view of the object', 'text overlays', 'fast moves'],
    studio: true,
  },
  'animate-still': {
    use: 'bringing an existing photo to life',
    subject: (s) => `The attached image of ${s}, brought to life. Keep the subject exactly as it is in the image.`,
    scene: 'The same scene as the image.',
    motion: 'Subtle, natural motion only: light, air, a slight camera drift. The subject keeps its shape.',
    camera: 'Matches the framing of the image.',
    avoid: ['change to the subject', 'new objects', 'text overlays', 'fast moves'],
    reference: true,
  },
};

const USAGE = `prompt.mjs — write a video prompt in the project's brand, sized and timed for the platform.

  node scripts/prompt.mjs --subject "..." [--type turntable] [--platform instagram_reel] [--variant square]
       [--size 1080x1920] [--seconds 7] [--reference] [--people] [--scene "..."] [--motion "..."]
       [--brand FILE] [--brand-mode full|minimal|none] [--paste "Tool name"] [--out DIR] [--force]
  node scripts/prompt.mjs sizes        every platform, variant, size and length range
  node scripts/prompt.mjs brand        which brand file is used and what was read from it

Types: ${Object.keys(TYPES).join(', ')}
Brand file: --brand, else BRAND_FILE, else brand.md, BRAND.md, brand/brand.md or docs/brand.md here.`;

function size(A) {
  let platform = 'custom';
  let variant = null;
  let w; let h; let min = 1; let max = 600; let def = 5;
  if (typeof A.size === 'string') {
    const m = /^(\d+)x(\d+)$/.exec(A.size);
    if (!m) throw new Error('--size must look like 1080x1920');
    w = Number(m[1]); h = Number(m[2]);
  } else {
    platform = typeof A.platform === 'string' ? A.platform : 'instagram_reel';
    const p = SIZES[platform];
    if (!p) throw new Error(`unknown platform "${platform}". See: node scripts/prompt.mjs sizes`);
    const v = typeof A.variant === 'string' ? A.variant : 'default';
    if (!p[v]) throw new Error(`${platform} has no "${v}" variant. It has: ${Object.keys(p).join(', ')}`);
    variant = v === 'default' ? null : v;
    [w, h, min, max, def] = p[v];
  }
  const seconds = A.seconds === undefined ? def : Number(A.seconds);
  if (!Number.isFinite(seconds) || seconds < min || seconds > max) throw new Error(`--seconds must be from ${min} to ${max} for ${platform}`);
  return { platform, variant, w, h, seconds };
}

export function build(A) {
  if (!A.subject || A.subject === true) throw new Error('--subject is needed: what the video shows');
  const type = typeof A.type === 'string' ? A.type : 'turntable';
  const t = TYPES[type];
  if (!t) throw new Error(`unknown type "${type}". Types: ${Object.keys(TYPES).join(', ')}`);
  const mode = typeof A['brand-mode'] === 'string' ? A['brand-mode'] : 'full';
  if (!['full', 'minimal', 'none'].includes(mode)) throw new Error('--brand-mode is full, minimal or none');
  const brandFile = mode === 'none' ? null : findBrand(typeof A.brand === 'string' ? A.brand : null);
  const brand = brandFile ? readBrand(brandFile) : null;
  const { platform, variant, w, h, seconds } = size(A);
  const reference = Boolean(A.reference || t.reference);
  const ratio = ratioOf(w, h);
  const orient = w === h ? 'square' : w > h ? 'horizontal' : 'vertical';

  const lines = [];
  if (reference && type !== 'animate-still') lines.push('Use the attached image as the exact reference for the subject: keep its shape, materials and colours. Build the motion and scene as described.');
  lines.push(`[SUBJECT] ${t.subject(A.subject)}`);
  if (A.people) lines.push('[PEOPLE] A person with the subject. The subject stays the hero and reads first.');
  lines.push(`[SCENE] ${typeof A.scene === 'string' ? A.scene : t.scene}`);
  // The brand's motion rules come after the shot's own, so the brand has the last word on pace.
  lines.push(`[MOTION] ${typeof A.motion === 'string' ? A.motion : t.motion}`);
  for (const [k, v] of Object.entries(styleBlock(brand, mode, { video: true, studio: Boolean(t.studio) }))) {
    lines.push(k === 'MOTION' ? `[BRAND MOTION] ${v}` : `[${k}] ${v}`);
  }
  lines.push(`[CAMERA] ${t.camera} ${orient[0].toUpperCase() + orient.slice(1)} ${ratio} frame.`);
  const brandAvoid = brand && mode !== 'none' ? brand.avoid : [];
  // The same rule from the shot and the brand is said once.
  const avoid = [...new Map([...t.avoid.map((a) => `No ${a}`), ...brandAvoid.map((a) => a[0].toUpperCase() + a.slice(1))]
    .map((a) => [a.toLowerCase().replace(/[^a-z0-9 ]/g, ''), a])).values()];
  lines.push(`[AVOID] ${avoid.join('. ')}.`);
  lines.push(`[LENGTH] ${seconds} seconds, ${ratio} ${orient}, ${w}x${h}. Ease in at the start and settle at the end so it loops or cuts cleanly.`);
  const prompt = lines.join('\n');

  // Seedance 2.5 is Higgsfield's default video model and takes 4 to 30 seconds. Longer
  // pieces are made from several clips; the prompt says so instead of asking for one.
  const clips = Math.ceil(seconds / 30);
  return {
    kind: 'video',
    subject: A.subject,
    type,
    platform,
    variant,
    width: w,
    height: h,
    aspect_ratio: ratio,
    seconds,
    prompt,
    avoid,
    reference,
    brand: brand ? { file: brand.file, mode, sections: brand.found } : { file: null, mode: mode === 'none' ? 'none' : 'none (no brand file found)' },
    higgsfield: {
      model: 'seedance_2_5',
      draft_model: 'kling3_0_turbo',
      aspect_ratio: nearestRatio(w, h),
      duration: Math.max(4, Math.ceil(seconds / clips)),
      clips,
      how: 'Give prompt.txt to the higgsfield-studio skill: its create command with --prompt-file, this model, --aspect_ratio and --duration, plus --image for a reference. It quotes the price before anything is spent; video is the expensive part, so try the draft model first. Check the model parameters with its run model get first.',
    },
  };
}

function pastePack(r, tool) {
  return `# ${tool}: ${r.subject}

Web tools change their screens often. These steps are kept general on purpose.

1. Open ${tool} and start a new video.
2. ${r.reference ? 'Attach the reference image (image to video).' : 'No reference image is needed (text to video).'}
3. Set the aspect ratio to ${r.higgsfield.aspect_ratio} and the length to ${r.seconds} seconds, or the nearest it offers.
4. Paste the whole of prompt.txt from this folder and generate.
5. If the motion is too fast, add "slow, subtle motion only". If text appears, ask for none.
6. Download the video${r.higgsfield.aspect_ratio === r.aspect_ratio ? '' : ` and crop it to ${r.width}x${r.height}`}.

Don't list: ${r.avoid.join('; ')}.
`;
}

const COMMANDS = {
  help() { console.log(USAGE); },
  sizes() {
    for (const [p, v] of Object.entries(SIZES)) {
      for (const [k, [w, h, min, max, def]] of Object.entries(v)) {
        console.log(`${p.padEnd(16)} ${k.padEnd(10)} ${String(w).padStart(5)}x${h}  ${ratioOf(w, h).padEnd(6)} ${min}-${max} s, default ${def}`);
      }
    }
  },
  brand(A) {
    const f = findBrand(typeof A.brand === 'string' ? A.brand : null);
    if (!f) { console.log('no brand file found. Prompts carry no brand style until one exists (see references/brand-file.md).'); return; }
    const b = readBrand(f);
    console.log(`brand file: ${f}`);
    console.log(`name: ${b.name || '(none)'}   sections read: ${b.found.join(', ') || 'none'}`);
    for (const k of ['palette', 'look', 'studio', 'motion', 'tone', 'avoid']) console.log(`  ${k.padEnd(8)} ${b[k].length} line(s)`);
  },
  write(A) {
    const r = build(A);
    const id = hash({ kind: r.kind, subject: r.subject, type: r.type, platform: r.platform, variant: r.variant, s: r.seconds, prompt: r.prompt });
    const seen = similar({ id, kind: 'video', platform: r.platform, subject: r.subject });
    if (seen.length && !A.force) {
      console.log('A similar prompt was already written in this project:');
      for (const s of seen.slice(-3)) console.log(`  ${s.at.slice(0, 10)}  ${s.type}  "${s.subject}"  -> ${s.out}`);
      console.log('Reuse it, or run again with --force to write a new one.');
      process.exitCode = 3;
      return;
    }
    const out = resolve(typeof A.out === 'string' ? A.out : join(home(), `${new Date().toISOString().slice(0, 10)}-video-${id}`));
    mkdirSync(out, { recursive: true });
    writeFileSync(join(out, 'prompt.txt'), `${r.prompt}\n`);
    writeFileSync(join(out, 'prompt.json'), `${JSON.stringify({ id, ...r }, null, 2)}\n`);
    if (typeof A.paste === 'string') writeFileSync(join(out, 'PASTE.md'), pastePack(r, A.paste));
    log({ id, kind: 'video', type: r.type, platform: r.platform, subject: r.subject, out });
    console.log(r.prompt);
    const hf = r.higgsfield;
    console.log(`\n${r.width}x${r.height} (${r.aspect_ratio}), ${r.seconds} s   brand: ${r.brand.file || r.brand.mode}   suggested Higgsfield model: ${hf.model} at ${hf.aspect_ratio}, ${hf.duration} s${hf.clips > 1 ? `, in ${hf.clips} clips` : ''} (draft: ${hf.draft_model})`);
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
