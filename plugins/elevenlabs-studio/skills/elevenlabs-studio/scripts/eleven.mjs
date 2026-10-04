#!/usr/bin/env node
// eleven.mjs — ElevenLabs voice-over, sound effects and music, spent on purpose.
//
// Every paid call goes through one door that prices it before it is made, never
// pays twice for the same request, and writes down what it actually cost.
//
// The four rules this file enforces:
//   1. Cache by request. The key is a hash of endpoint + body. Asking again for the
//      same thing returns the file already paid for. --fresh is the only way past it.
//   2. Estimate before calling, from the published rates in RATE. They are estimates.
//   3. Measure after calling. Credits used are read from /v1/user/subscription before
//      and after, and both numbers go in the ledger. The measured one is the truth.
//      Text to speech is measured exactly, from the history item whose request_id matches
//      the response. Other calls fall back to the balance, which settles a few seconds
//      after the response, so it is polled until it moves. A difference of 0 means "not
//      settled yet", never "free". Nothing after a paid call may crash: an unmeasured
//      call is logged with measured: null.
//   4. Keep a reserve. A call that would leave fewer than ELEVEN_RESERVE credits
//      (default 1000) is refused, so one bad loop cannot empty the month.
//
// The API key is read from the shared credential store and used in-process. It is
// never printed, never passed on a command line, and never written to the ledger.

import { readFileSync, writeFileSync, existsSync, mkdirSync, appendFileSync, copyFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { join, dirname, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { readSecrets, providerPath } from '../lib/store.mjs';

const API = 'https://api.elevenlabs.io';
const PROVIDER = 'elevenlabs';
const KEY = 'ELEVENLABS_API_KEY';
const USER_AGENT = 'itqan-agent-toolkit/1.0 (+https://github.com/itqanlab/agent-toolkit)';

export const RESERVE = Number(process.env.ELEVEN_RESERVE || 1000);

// Where the cache and the ledger live: per project, under the folder the command is run
// from, so each project keeps its own record. ELEVENLABS_HOME moves it.
export const home = () => resolve(process.env.ELEVENLABS_HOME || join(process.cwd(), '.elevenlabs'));
const cacheDir = () => join(home(), 'cache');
const ledgerPath = () => join(home(), 'ledger.jsonl');

// Published estimates. They are not a price list from the API. The ledger's measured
// column is the truth; change these when the two keep disagreeing.
const RATE = {
  // Measured on a Creator plan: eleven_v3 and eleven_multilingual_v2 both cost about 0.45 a
  // character (66 for 151, 51 for 115, and many short lines agree). Published was 1.
  // Flash and turbo at 0.25 is an assumption (half of that), not yet measured.
  // Other models keep the published 1.
  ttsPerChar: (model) => (/flash|turbo/.test(model) ? 0.25 : /eleven_v3|multilingual_v2/.test(model) ? 0.45 : 1),
  // Published, used only when the model picks the length.
  sfxPerGen: 200,
  // Measured: with duration_seconds set, 2.6 s cost 29 credits, three times out of three.
  sfxPerSec: 11.2,
  // Measured, not published: a 44.5 s music_v1 render cost 612 credits (about 825 a minute).
  // The published figure was 900.
  musicPerMin: 825,
};

// What each kind of call needs switched on for the key, in ElevenLabs' own words.
const PERMISSION = {
  '/v1/user': 'User: Read',
  '/v1/history': 'History: Read',
  '/v1/text-to-speech': 'Text to Speech: Access',
  '/v1/sound-generation': 'Sound Effects: Access',
  '/v1/music': 'Music: Access',
  '/v2/voices': 'Voices: Read',
  '/v1/shared-voices': 'Voices: Read',
};

export class ElevenError extends Error {
  constructor(message, { status, code = 1 } = {}) {
    super(message);
    this.name = 'ElevenError';
    this.status = status;
    this.code = code;
  }
}

// ---------------------------------------------------------------- plumbing

export function getKey() {
  const key = readSecrets(PROVIDER)[KEY];
  if (!key || /^(<|paste|your[-_])/i.test(key)) {
    throw new ElevenError(
      'ElevenLabs is not connected yet. The key goes in this file:\n' +
      `  ${providerPath(PROVIDER)}\n\n` +
      'Run the guided setup, which creates that file and says where to get the key:\n' +
      '  node scripts/setup.mjs begin',
      { code: 2 },
    );
  }
  return key;
}

function permissionFor(path) {
  const hit = Object.keys(PERMISSION).find((p) => path.startsWith(p));
  return hit ? PERMISSION[hit] : null;
}

/** Turn an ElevenLabs error body into something a person can act on. */
function explain(method, path, status, text) {
  let detail = {};
  try { detail = JSON.parse(text).detail || {}; } catch { /* plain text */ }
  const said = typeof detail === 'string' ? detail : detail.message || text.slice(0, 300);
  const code = typeof detail === 'object' ? detail.status || detail.code || '' : '';
  const perm = permissionFor(path);

  if (status === 401 && /permission/i.test(`${code} ${said}`)) {
    return `The key is missing a permission${perm ? `: ${perm}` : ''}.\n` +
      'Open https://elevenlabs.io/app/settings/api-keys, edit the key, switch that row on, and save.\n' +
      'The key itself stays the same, so nothing needs to be pasted again.';
  }
  if (status === 401) {
    return 'ElevenLabs did not accept the key. It may have been deleted, or only part of it was pasted.\n' +
      'Replace it with:  node scripts/setup.mjs begin --force';
  }
  if (status === 402 || /quota|credits?/i.test(code)) {
    return `ElevenLabs refused for lack of credits or a plan limit: ${said}`;
  }
  if (status === 429) {
    return `ElevenLabs is rate-limiting this account (too many requests at once). Wait a little and try again. ${said}`;
  }
  if (status === 422 || status === 400) {
    return `ElevenLabs rejected the request as invalid. Nothing was charged.\n  ${said}`;
  }
  return `${method} ${path} failed with HTTP ${status}: ${said}`;
}

/** One call against the API. Returns the parsed JSON, or the raw Response with { raw: true }. */
export async function call(method, path, body, { raw = false, key } = {}) {
  const init = {
    method,
    headers: {
      'xi-api-key': key || getKey(),
      'User-Agent': USER_AGENT,
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  };
  let res;
  try {
    res = await fetch(API + path, init);
  } catch (err) {
    throw new ElevenError(`Could not reach ElevenLabs (${err.message}). Check the internet connection and try again.`);
  }
  if (!res.ok) throw new ElevenError(explain(method, path.split('?')[0], res.status, await res.text()), { status: res.status });
  return raw ? res : res.json();
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

/** Credits used and left this period. Free to call; needs the User: Read permission. */
export async function credits(opts = {}) {
  // The endpoint is rate-limited: polling it every 2.5 s drew 429s. Back off 3, 6, 9... s.
  let s;
  for (let i = 0; ; i += 1) {
    try { s = await call('GET', '/v1/user/subscription', undefined, opts); break; } catch (err) {
      if (err.status !== 429 || i >= 5) throw err;
      await wait(3000 * (i + 1));
    }
  }
  return {
    used: s.character_count,
    limit: s.character_limit,
    left: s.character_limit - s.character_count,
    tier: s.tier,
    reset: s.next_character_count_reset_unix,
  };
}

/**
 * The exact cost of one call, from its history item: character_count_change_to minus
 * character_count_change_from. Text to speech has one, matched by the request-id header.
 * Music and sound effects may not, and then this returns null. Never throws.
 */
async function exactCost(requestId) {
  for (let i = 0; requestId && i < 4; i += 1) {
    await wait(1500);
    try {
      const h = await call('GET', '/v1/history?page_size=20');
      const item = (h.history || []).find((x) => x.request_id === requestId);
      if (item && Number.isFinite(item.character_count_change_to) && Number.isFinite(item.character_count_change_from)) {
        return item.character_count_change_to - item.character_count_change_from;
      }
    } catch { return null; }
  }
  return null;
}

/**
 * Read the balance after a call. ElevenLabs updates it a few seconds after the response:
 * a music render read straight away showed 0, and 612 a little later. When the cost is not
 * already known, a paid call is polled every 4 s (no faster, the endpoint is rate-limited)
 * for up to about 30 s until the count moves. Never throws: null means it could not be read.
 */
async function settle(before, poll) {
  let after = await credits().catch(() => null);
  for (let i = 0; poll && i < 8 && (!after || after.used === before.used); i += 1) {
    await wait(4000);
    after = await credits().catch(() => after);
  }
  return after;
}

const hash = (o) => createHash('sha256').update(JSON.stringify(o)).digest('hex').slice(0, 16);

function extFor(format = '') {
  if (format.startsWith('mp3')) return '.mp3';
  if (format.startsWith('wav')) return '.wav';
  if (format.startsWith('opus')) return '.opus';
  if (format.startsWith('pcm')) return '.pcm';
  return '.raw';
}

function ledger(row) {
  mkdirSync(home(), { recursive: true });
  appendFileSync(ledgerPath(), `${JSON.stringify({ at: new Date().toISOString(), ...row })}\n`);
}

function deliver(cached, out, withMeta) {
  if (!out) return;
  mkdirSync(dirname(resolve(out)), { recursive: true });
  copyFileSync(cached, out);
  if (withMeta && existsSync(`${cached}.json`)) copyFileSync(`${cached}.json`, `${out}.json`);
}

// One paid request: estimate, guard, cache, call, measure, ledger.
async function paid(kind, endpoint, body, opts, estimate, onResponse) {
  const id = hash({ endpoint, body });
  const cached = join(cacheDir(), id + (opts.ext || '.mp3'));
  const hit = existsSync(cached) && !opts.fresh;
  const est = Math.round(estimate);

  console.log(`${kind}: estimate ~${est} credits (from the rate table, not a quote)   cache ${id}${hit ? '   HIT, would cost 0' : ''}`);

  if (opts.dry) {
    if (opts.max && estimate > Number(opts.max)) console.log(`would be refused: estimate ${est} is above --max ${opts.max}`);
    console.log(JSON.stringify({ endpoint, body }, null, 2));
    console.log('dry run. Nothing was called and nothing was spent.');
    return;
  }
  if (opts.fresh && (!opts.why || opts.why === true)) {
    throw new ElevenError('--fresh pays again for a request already in the cache. Say why with --why "...".', { code: 3 });
  }
  if (opts.max && estimate > Number(opts.max)) {
    throw new ElevenError(`refused: estimate ${est} is above --max ${opts.max}. Nothing was spent.`, { code: 3 });
  }
  if (hit) {
    deliver(cached, opts.out, true);
    console.log(`cache hit, 0 credits. ${opts.out ? `-> ${opts.out}` : cached}`);
    return;
  }

  getKey();
  const before = await credits();
  if (estimate > 0 && before.left - estimate < RESERVE) {
    throw new ElevenError(
      `refused: ${before.left} credits left, this would use about ${est}, and the reserve is ${RESERVE}.\n` +
      'Lower the reserve for this run with ELEVEN_RESERVE=<n> only if the user agrees.',
      { code: 3 },
    );
  }

  const res = await call('POST', endpoint, body, { raw: true });
  mkdirSync(cacheDir(), { recursive: true });
  const meta = await onResponse(res, cached);
  // From here on the money is spent, so nothing may throw before the ledger row is written.
  const requestId = res.headers.get('request-id');
  const exact = await exactCost(requestId);
  const after = await settle(before, exact === null && estimate > 0);
  // Back-to-back calls blur a balance delta, so the history figure wins when there is one.
  // No movement on a paid call means the balance had not settled, not that it was free.
  const delta = after && (after.used !== before.used || estimate === 0) ? after.used - before.used : null;
  const measured = exact !== null ? exact : delta;
  // When history gave the cost but the balance has not caught up yet, count it ourselves.
  const left = after ? (exact !== null && after.used === before.used ? after.left - exact : after.left) : null;
  deliver(cached, opts.out, Boolean(meta));

  ledger({
    kind,
    cache: id,
    estimate: est,
    measured,
    left,
    settled: measured !== null,
    measured_by: exact !== null ? 'history' : delta !== null ? 'balance' : null,
    tag: typeof opts.tag === 'string' ? opts.tag : null,
    why: typeof opts.why === 'string' ? opts.why : null,
    out: typeof opts.out === 'string' ? opts.out : null,
    request_id: requestId,
    body,
  });
  if (measured === null) {
    console.log('note: the cost could not be measured (no history item, and the balance had not moved or could not be read). The ledger row says settled: false. Check with: node scripts/eleven.mjs account');
  }
  console.log(
    `done. measured ${measured ?? 'unknown'} credits${exact !== null ? ' (exact, from history)' : ''} (estimate ${est}), ${left ?? '?'} left. ` +
    `${opts.out ? `-> ${opts.out}` : cached}`,
  );
  if (measured !== null && measured > 0 && Math.abs(measured - est) > Math.max(50, est * 0.5)) {
    console.log(exact !== null
      ? 'note: the exact cost is far from the estimate. The rate table may be wrong for this model; check the ledger before the next batch.'
      : 'note: the measured cost is far from the estimate. Another job on the same account at the same time also counts.');
  }
}

const saveBinary = async (res, file) => { writeFileSync(file, Buffer.from(await res.arrayBuffer())); };

// ---------------------------------------------------------------- arguments

function parseArgs(argv) {
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

function need(A, cmd, ...names) {
  const missing = names.filter((n) => !A[n] || A[n] === true);
  if (missing.length) throw new ElevenError(`${cmd} needs ${missing.map((n) => `--${n}`).join(' ')}. See: node scripts/eleven.mjs help`);
}

function number(A, name, min, max) {
  if (A[name] === undefined) return undefined;
  const n = Number(A[name]);
  if (!Number.isFinite(n) || n < min || n > max) throw new ElevenError(`--${name} must be a number from ${min} to ${max}`);
  return n;
}

function json(value, name) {
  try { return JSON.parse(value); } catch { throw new ElevenError(`--${name} is not valid JSON: ${value}`); }
}

const USAGE = `eleven.mjs — ElevenLabs voice-over, sound effects and music, with a credit guard.

Free:
  account                                   plan, credits used and left, reset date
  voices [--q calm] [--lang en] [--library] [--previews DIR]
                                            list voices. --library searches the shared library
                                            (--lang filters it). --previews saves the free samples
  plan --prompt "..." --ms 45000 --out plan.json [--model music_v1]
                                            a music composition plan, no credits
  ledger                                    what has been spent, by kind and by tag

Paid:
  tts   --voice ID --text "..." --out f.mp3 [--model eleven_v3] [--timestamps]
        [--prev "..."] [--next "..."] [--settings '{"stability":0.5}'] [--lang en] [--format mp3_44100_128]
  sfx   --text "..." --out f.mp3 [--duration 2.5] [--influence 0.6] [--loop] [--format ...]
  music (--plan plan.json | --prompt "..." --ms 45000) --out f.mp3 [--model music_v1]
        [--instrumental] [--format ...]

Every paid command also takes:
  --dry        print the estimate and the request, call nothing
  --max N      refuse if the estimate is above N credits
  --fresh      skip the cache and pay again (needs --why)
  --tag NAME   group this call in the ledger, for example by project or scene
  --why "..."  one line on what this is for
  --out FILE   where to write the result (a copy of the cached file)

Cache and ledger: ${home()}   (ELEVENLABS_HOME moves it)
Reserve: ${RESERVE} credits   (ELEVEN_RESERVE changes it)`;

// ---------------------------------------------------------------- commands

const COMMANDS = {
  help() { console.log(USAGE); },

  async account() {
    const c = await credits();
    const reset = c.reset ? new Date(c.reset * 1000).toISOString().slice(0, 10) : 'unknown';
    console.log(`plan ${c.tier}   used ${c.used} of ${c.limit}   left ${c.left}   resets ${reset}`);
    console.log(`reserve ${RESERVE}   so paid calls can spend up to ${Math.max(0, c.left - RESERVE)} now`);
    console.log(`cache and ledger: ${home()}`);
  },

  async voices(A) {
    let list;
    if (A.library) {
      const q = new URLSearchParams({ page_size: '30', ...(typeof A.q === 'string' ? { search: A.q } : {}), ...(typeof A.lang === 'string' ? { language: A.lang } : {}) });
      list = (await call('GET', `/v1/shared-voices?${q}`)).voices.map((v) => ({
        id: v.voice_id, name: v.name,
        labels: [v.gender, v.age, v.accent, v.language, v.use_case, v.descriptive].filter(Boolean).join(', '),
        preview: v.preview_url,
      }));
    } else {
      const q = new URLSearchParams({ page_size: '100', ...(typeof A.q === 'string' ? { search: A.q } : {}) });
      list = (await call('GET', `/v2/voices?${q}`)).voices.map((v) => ({
        id: v.voice_id, name: v.name, labels: Object.values(v.labels || {}).join(', '), preview: v.preview_url,
      }));
    }
    if (!list.length) console.log('no voices matched');
    for (const v of list) console.log(`${v.id}  ${String(v.name).padEnd(28)} ${v.labels}`);
    if (A.previews && A.previews !== true) {
      // preview_url is a static sample ElevenLabs hosts. Fetching it costs no credits.
      mkdirSync(A.previews, { recursive: true });
      let saved = 0;
      for (const v of list) {
        if (!v.preview) continue;
        const file = join(A.previews, `${String(v.name).replace(/[^\w-]+/g, '_')}-${v.id}.mp3`);
        if (existsSync(file)) continue;
        const res = await fetch(v.preview).catch(() => null);
        if (!res || !res.ok) continue;
        writeFileSync(file, Buffer.from(await res.arrayBuffer()));
        saved += 1;
      }
      console.log(`${saved} preview(s) saved to ${A.previews}. Free.`);
    }
  },

  async tts(A) {
    need(A, 'tts', 'voice', 'text');
    const model = typeof A.model === 'string' ? A.model : 'eleven_v3';
    const format = typeof A.format === 'string' ? A.format : 'mp3_44100_128';
    // eleven_v3 answers previous_text / next_text with a 400 ("not yet supported"). Refuse here,
    // with the fix, instead of a round trip.
    if (model === 'eleven_v3' && (A.prev || A.next)) {
      throw new ElevenError('--prev and --next are not supported on eleven_v3. Drop them, or stitch with --model eleven_multilingual_v2.');
    }
    const body = {
      text: A.text,
      model_id: model,
      ...(A.settings ? { voice_settings: json(A.settings, 'settings') } : {}),
      ...(typeof A.prev === 'string' ? { previous_text: A.prev } : {}),
      ...(typeof A.next === 'string' ? { next_text: A.next } : {}),
      ...(typeof A.lang === 'string' ? { language_code: A.lang } : {}),
    };
    const ts = Boolean(A.timestamps);
    const endpoint = `/v1/text-to-speech/${encodeURIComponent(A.voice)}${ts ? '/with-timestamps' : ''}?output_format=${format}`;
    await paid('tts', endpoint, body, { ...A, ext: extFor(format) }, A.text.length * RATE.ttsPerChar(model), async (res, file) => {
      if (!ts) return saveBinary(res, file);
      // with-timestamps answers JSON: base64 audio plus per-character timing,
      // which is what a picture can be cut to.
      const j = await res.json();
      writeFileSync(file, Buffer.from(j.audio_base64, 'base64'));
      writeFileSync(`${file}.json`, JSON.stringify({ alignment: j.alignment, normalized_alignment: j.normalized_alignment }, null, 1));
      return true;
    });
  },

  async sfx(A) {
    need(A, 'sfx', 'text');
    const format = typeof A.format === 'string' ? A.format : 'mp3_44100_128';
    const duration = number(A, 'duration', 0.5, 30);
    const influence = number(A, 'influence', 0, 1);
    const body = {
      text: A.text,
      model_id: 'eleven_text_to_sound_v2',
      ...(duration !== undefined ? { duration_seconds: duration } : {}),
      ...(influence !== undefined ? { prompt_influence: influence } : {}),
      ...(A.loop ? { loop: true } : {}),
    };
    await paid('sfx', `/v1/sound-generation?output_format=${format}`, body, { ...A, ext: extFor(format) }, duration !== undefined ? duration * RATE.sfxPerSec : RATE.sfxPerGen, saveBinary);
  },

  async plan(A) {
    need(A, 'plan', 'prompt', 'ms', 'out');
    const ms = number(A, 'ms', 3000, 600000);
    const body = { prompt: A.prompt, music_length_ms: ms, model_id: typeof A.model === 'string' ? A.model : 'music_v1' };
    // ElevenLabs documents the composition plan endpoint as free. It is still measured.
    await paid('music-plan', '/v1/music/plan', body, { ...A, ext: '.json' }, 0, async (res, file) => {
      writeFileSync(file, JSON.stringify(await res.json(), null, 2));
    });
  },

  async music(A) {
    need(A, 'music', 'out');
    // music_v1 is the default on purpose: it is the only model that holds each section to its
    // duration_ms (respect_sections_durations). The v2 models ignore section lengths, so their
    // music cannot be cut to a picture.
    const model = typeof A.model === 'string' ? A.model : 'music_v1';
    const format = typeof A.format === 'string' ? A.format : 'mp3_44100_128';
    let body;
    let ms;
    if (A.plan && A.plan !== true) {
      const plan = json(readFileSync(A.plan, 'utf8'), 'plan');
      const parts = plan.sections || plan.chunks || [];
      ms = parts.reduce((s, c) => s + (c.duration_ms || 0), 0);
      if (model === 'music_v1' && plan.chunks) console.log('warning: this plan has "chunks", the v2 shape. music_v1 expects "sections". Make the plan with the same --model.');
      if (model !== 'music_v1' && plan.sections) console.log(`warning: this plan has "sections", the music_v1 shape, but --model is ${model}.`);
      body = { composition_plan: plan, model_id: model, ...(model === 'music_v1' ? { respect_sections_durations: true } : {}) };
    } else {
      need(A, 'music', 'prompt', 'ms');
      ms = number(A, 'ms', 3000, 600000);
      body = { prompt: A.prompt, music_length_ms: ms, model_id: model, ...(A.instrumental ? { force_instrumental: true } : {}) };
    }
    await paid('music', `/v1/music?output_format=${format}`, body, { ...A, ext: extFor(format) }, (ms / 60000) * RATE.musicPerMin, saveBinary);
  },

  ledger() {
    if (!existsSync(ledgerPath())) { console.log(`nothing spent yet (no ledger at ${ledgerPath()})`); return; }
    const rows = readFileSync(ledgerPath(), 'utf8').trim().split('\n').filter(Boolean).map((l) => JSON.parse(l));
    const group = (k) => rows.reduce((m, r) => {
      const g = r[k] || '(none)';
      m[g] ??= { calls: 0, estimate: 0, measured: 0 };
      m[g].calls += 1;
      m[g].estimate += r.estimate || 0;
      m[g].measured += r.measured || 0;
      return m;
    }, {});
    const show = (title, groups) => {
      console.log(title);
      for (const [g, v] of Object.entries(groups)) {
        console.log(`  ${g.padEnd(24)} ${String(v.calls).padStart(4)} calls   measured ${String(v.measured).padStart(7)}   estimated ${v.estimate}`);
      }
    };
    show('by kind', group('kind'));
    show('by tag', group('tag'));
    const measured = rows.reduce((s, r) => s + (r.measured || 0), 0);
    const estimate = rows.reduce((s, r) => s + (r.estimate || 0), 0);
    console.log(`total: ${measured} credits measured, ${estimate} estimated, over ${rows.length} paid calls`);
    const unsettled = rows.filter((r) => r.measured === null).length;
    if (unsettled) console.log(`${unsettled} call(s) were never measured (the balance had not settled), so the measured total is low`);
    console.log(`ledger: ${ledgerPath()}`);
  },
};

// pathToFileURL, not string concatenation: a Windows path like C:\... is not a valid URL.
const isMain = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
if (isMain) {
  const A = parseArgs(process.argv.slice(2));
  const cmd = A._[0] || 'help';
  const handler = COMMANDS[A.help || cmd === '--help' ? 'help' : cmd];
  if (!handler) {
    console.error(`unknown command "${cmd}"\n`);
    console.error(USAGE);
    process.exit(1);
  }
  try {
    await handler(A);
  } catch (err) {
    console.error(err instanceof ElevenError ? err.message : `error: ${err.message}`);
    process.exit(err.code || 1);
  }
}
