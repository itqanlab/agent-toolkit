#!/usr/bin/env node
// hf.mjs — Higgsfield image, video, audio and 3D generation, spent on purpose.
//
// It wraps the official `higgsfield` command line tool. Every paid call goes through one door
// that prices it before it is made, never pays twice for the same request, and writes down
// what it actually cost.
//
// The rules this file enforces:
//   1. Quote before paying. Higgsfield prices a job for free (`generate cost`, `--cost-only`,
//      or `--enhance-only` plus `generate cost` for each planned image). The quote is shown
//      before anything is spent. A call that cannot be quoted needs --yes.
//   2. Cache by request. The key is a hash of the command, its parameters and the content of
//      every local file it uses. The same request returns the files already paid for.
//      --fresh is the only way past it, and it needs a reason in --why.
//   3. Measure after. Higgsfield's transaction list shows what each job really cost, but not
//      which job it was, so the tool counts the spends that appear after the newest one it saw
//      before the call. The balance before and after is the fallback.
//   4. Keep a reserve. A call that would leave fewer than HF_RESERVE credits is refused.
//   5. Outward actions (deploying or publishing a website, training a Soul, changing the
//      billing workspace) run only through `act`, with --yes.
//
// Sign-in belongs to the CLI (browser OAuth). This file never prints a token and never reads
// the CLI's credential file.

import { spawn } from 'node:child_process';
import { readFileSync, writeFileSync, existsSync, mkdirSync, appendFileSync, copyFileSync, statSync, unlinkSync, realpathSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { join, dirname, resolve, extname, basename } from 'node:path';
import { pathToFileURL } from 'node:url';

export const home = () => resolve(process.env.HIGGSFIELD_HOME || join(process.cwd(), '.higgsfield'));

// A project can pin its settings in <home>/config.json: { "account": "...", "reserve": 10 }.
// The account matters because the CLI login is machine-wide, and a free account looks just like
// the paid one until a job runs on the wrong side.
const config = (() => {
  try { return JSON.parse(readFileSync(join(home(), 'config.json'), 'utf8')); } catch { return {}; }
})();
const ACCOUNT = process.env.HF_ACCOUNT || config.account || null;

// Basic plans hold tens of credits, so the default is small: enough to stop a loop from taking
// the account to zero, not so large that it blocks normal work. Raise it on bigger plans.
export const RESERVE = Number(process.env.HF_RESERVE ?? config.reserve ?? 5);
const cacheDir = () => join(home(), 'cache');
const ledgerPath = () => join(home(), 'ledger.jsonl');
const uploadsPath = () => join(home(), 'uploads.json');

export class HfError extends Error {
  constructor(message, { code = 1 } = {}) {
    super(message);
    this.name = 'HfError';
    this.code = code;
  }
}

// ---------------------------------------------------------------- the CLI

// On Windows npm installs a .cmd shim, and Node will not start one without a shell. The shim
// only starts vendor/hf.exe, so start that directly and keep argument quoting out of cmd.exe.
function binary() {
  if (process.env.HIGGSFIELD_BIN) return process.env.HIGGSFIELD_BIN;
  if (process.platform !== 'win32') return 'higgsfield';
  const roots = [process.env.APPDATA && join(process.env.APPDATA, 'npm', 'node_modules')].filter(Boolean);
  for (const r of roots) {
    const exe = join(r, '@higgsfield', 'cli', 'vendor', 'hf.exe');
    if (existsSync(exe)) return exe;
  }
  return 'higgsfield.exe';
}

/** Run the CLI. Resolves { code, out, err }. With progress, its stderr is shown as it comes. */
function exec(args, { progress = false, interactive = false } = {}) {
  return new Promise((done, failed) => {
    const child = spawn(binary(), args, { stdio: interactive ? 'inherit' : ['ignore', 'pipe', 'pipe'] });
    let out = '';
    let err = '';
    child.stdout?.on('data', (d) => { out += d; });
    child.stderr?.on('data', (d) => { err += d; if (progress) process.stderr.write(d); });
    child.on('error', (e) => failed(e.code === 'ENOENT'
      ? new HfError('The Higgsfield command line tool is not installed on this machine.\n' +
        'Check and install it with:  sh scripts/setup-deps.sh   (Windows: .\\scripts\\setup-deps.ps1)', { code: 2 })
      : e));
    child.on('close', (code) => done({ code, out, err }));
  });
}

/** Turn what the CLI printed on failure into something a person can act on. */
function explain(text) {
  const said = text.replace(/^Error:\s*/m, '').trim();
  if (/session expired|not authenticated|not logged in|unauthori[sz]ed|login required/i.test(said)) {
    return 'Higgsfield is not signed in on this machine. Sign in once with:\n' +
      '  higgsfield auth login\n' +
      'It opens the browser. Nothing was charged.';
  }
  if (/no workspace selected/i.test(said)) {
    return 'Higgsfield has no billing workspace selected, which happens after a fresh sign-in.\n' +
      'List them with  higgsfield workspace list  and pick one with  higgsfield workspace set <id>.\nNothing was charged.';
  }
  if (/insufficient|not enough credits|out of credits/i.test(said)) {
    return `Higgsfield refused for lack of credits: ${said}`;
  }
  if (/unknown params/i.test(said) || /missing required params/i.test(said) || /invalid values/i.test(said)) {
    return `Higgsfield rejected the request: ${said}\n` +
      'Check what the model accepts with:  node scripts/hf.mjs run model get <model>\nNothing was charged.';
  }
  if (/no model with job_type/i.test(said)) {
    return `${said}\nList the models with:  node scripts/hf.mjs run model list`;
  }
  return `Higgsfield said: ${said.slice(0, 600)}`;
}

/** Run a CLI command with --json and parse the answer. Throws a readable HfError on failure. */
async function cliJson(args, opts) {
  const r = await exec([...args, '--json'], opts);
  if (r.code !== 0) throw new HfError(explain(r.err || r.out));
  try { return JSON.parse(r.out); } catch {
    throw new HfError(`Higgsfield answered something that is not JSON:\n${r.out.slice(0, 400)}`);
  }
}

// ---------------------------------------------------------------- account

export async function balance() {
  const s = await cliJson(['account', 'status']);
  return { credits: Number(s.credits), plan: s.subscription_plan_type || s.plan || 'unknown', email: s.email || null };
}

/** Refuse to spend on an account other than the one the project names. */
function checkAccount(b) {
  if (!ACCOUNT || !b.email || b.email.toLowerCase() === ACCOUNT.toLowerCase()) return;
  throw new HfError(
    `refused: signed in as ${b.email} (${b.plan}, ${show(b.credits)} credits), but this project spends from ${ACCOUNT}.\n` +
    `Switch with  higgsfield auth logout  then  higgsfield auth login  as ${ACCOUNT}. Nothing was spent.`, { code: 4 });
}

/**
 * One paid job at a time per project. Spends are matched by time, so two jobs running together
 * would each count the other's charge (a 0.23 voice line was once logged as 10.23 that way).
 * A lock left by a process that has died is taken over.
 */
async function lock() {
  const file = join(home(), '.lock');
  mkdirSync(home(), { recursive: true });
  for (let waited = 0; ; waited += 1) {
    try { writeFileSync(file, String(process.pid), { flag: 'wx' }); break; } catch {
      let alive = false;
      try { process.kill(Number(readFileSync(file, 'utf8')), 0); alive = true; } catch { /* gone */ }
      if (!alive) { writeFileSync(file, String(process.pid)); break; }
      if (waited === 0) console.log('waiting for another paid Higgsfield job in this project to finish...');
      await wait(3000);
    }
  }
  const release = () => { try { if (readFileSync(file, 'utf8') === String(process.pid)) unlinkSync(file); } catch { /* already gone */ } };
  process.on('exit', release);
  return release;
}

async function transactions() {
  const t = await cliJson(['account', 'transactions', '--size', '50']);
  return Array.isArray(t) ? t : t.items || [];
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * What the call cost. Spends that appear after the newest transaction seen before the call are
 * counted. Settles a few seconds late, so it polls for up to about 30 s. Never throws.
 */
async function measure(before, baseline, expectSpend) {
  let spends = [];
  let after = null;
  for (let i = 0; i < 10; i += 1) {
    try {
      const list = await transactions();
      spends = list.filter((t) => t.action === 'spend' && (!baseline || t.created_at > baseline));
      after = await balance();
    } catch { /* keep the last reading */ }
    if (!expectSpend || spends.length || (after && after.credits !== before.credits)) break;
    await wait(3000);
  }
  const fromTx = spends.length ? Math.round(spends.reduce((s, t) => s - Number(t.credits), 0) * 100) / 100 : null;
  const fromBalance = after && after.credits !== before.credits ? Math.round((before.credits - after.credits) * 100) / 100 : null;
  return {
    measured: fromTx ?? fromBalance,
    measured_by: fromTx !== null ? 'transactions' : fromBalance !== null ? 'balance' : null,
    items: spends.map((t) => `${t.display_name}: ${-Number(t.credits)}`),
    left: after ? after.credits : null,
  };
}

// ---------------------------------------------------------------- arguments

const GUARD_BOOL = new Set(['dry', 'fresh', 'yes']);
const GUARD_VALUE = new Set(['max', 'tag', 'why', 'out', 'prompt-file', 'timeout']);

/** Take this tool's own flags out of argv. The rest goes to the CLI untouched. */
function splitGuard(argv) {
  const g = {};
  const rest = [];
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    const name = a.startsWith('--') ? a.slice(2).split('=')[0] : null;
    if (name && GUARD_BOOL.has(name)) { g[name] = true; continue; }
    if (name && GUARD_VALUE.has(name)) {
      if (a.includes('=')) g[name] = a.slice(a.indexOf('=') + 1);
      else { g[name] = argv[i + 1]; i += 1; }
      continue;
    }
    rest.push(a);
  }
  // A long prompt is safer in a file than in a shell argument: quotes and line breaks survive.
  if (g['prompt-file']) {
    if (!isFile(g['prompt-file'])) throw new HfError(`--prompt-file: no such file ${g['prompt-file']}`);
    rest.push('--prompt', readFileSync(g['prompt-file'], 'utf8').trim());
  }
  return { g, rest };
}

const ALIAS = {
  gen: 'generate', ms: 'marketing-studio', marketing: 'marketing-studio', acc: 'account',
  ws: 'workspace', websites: 'website', cards: 'marketplace-cards', 'marketplace-card': 'marketplace-cards',
  presets: 'preset', dtc: 'dtc-ads', ads: 'dtc-ads',
};
const words = (args) => args.filter((a) => !a.startsWith('-')).slice(0, 3).map((w) => ALIAS[w] || w);

// Commands that spend credits have their own guarded entry here, so `run` refuses them.
function paidRoute(args) {
  const [a, b, c] = words(args);
  const has = (f) => args.includes(f);
  if (a === 'generate' && b === 'create') return 'create';
  if (a === 'generate' && b === 'workflow') return 'workflow';
  if (a === 'product-photoshoot' && b === 'create' && !has('--enhance-only')) return 'photoshoot';
  if (a === 'marketplace-cards' && b === 'create' && !has('--enhance-only')) return 'cards';
  if (a === 'marketing-studio' && b === 'dtc-ads' && c === 'generate' && !has('--cost-only')) return 'dtc';
  return null;
}

// Commands that act on the outside world, or cannot be undone, or print a secret.
function isAct(args) {
  const [a, b, c] = words(args);
  if (a === 'auth' && b === 'logout') return true;
  if (a === 'soul-id' && b === 'create') return true;
  if (a === 'workspace' && (b === 'set' || b === 'unset')) return true;
  if (a === 'website' && ['create', 'deploy', 'publish', 'rename', 'contest', 'repo-access'].includes(b)) return true;
  if (a === 'website' && b === 'secrets' && (c === 'set' || c === 'delete')) return true;
  return [b, c].some((w) => w === 'delete' || w === 'remove');
}

// ---------------------------------------------------------------- local files

const MEDIA = /\.(png|jpe?g|webp|gif|heic|avif|bmp|tiff?|mp4|mov|webm|m4v|mkv|mp3|wav|m4a|aac|ogg|flac|pdf|txt|md|docx?)$/i;
const sha = (buf) => createHash('sha256').update(buf).digest('hex');
const fileHash = (p) => sha(readFileSync(p)).slice(0, 32);
const isFile = (p) => { try { return statSync(p).isFile(); } catch { return false; } };

function readUploads() {
  try { return JSON.parse(readFileSync(uploadsPath(), 'utf8')); } catch { return {}; }
}

/**
 * Hash every local file the request uses, so a changed photo is a new request. With upload,
 * also replace each media path with an upload id, uploading each file once (uploads are free)
 * so the quote and the job use the same input and it is never sent twice.
 */
async function prepare(args, { upload }) {
  const out = [];
  const key = [];
  const uploads = readUploads();
  let changed = false;
  for (const a of args) {
    // The guard adds --json and --wait itself, where the command takes them.
    if (a === '--json' || a === '--wait') continue;
    if (a.startsWith('@') && isFile(a.slice(1))) { out.push(a); key.push(`@${fileHash(a.slice(1))}`); continue; }
    // A media value may carry a role after a colon (dtc-ads: ./photo.png:image).
    const m = /^(.*?)(:[a-z_]+)?$/.exec(a);
    const path = isFile(a) ? a : m && isFile(m[1]) ? m[1] : null;
    if (!a.startsWith('-') && path && MEDIA.test(path)) {
      const h = fileHash(path);
      const role = path === a ? '' : a.slice(path.length);
      key.push(`file:${h}${role}`);
      if (!upload) { out.push(a); continue; }
      if (!uploads[h]) {
        const u = await cliJson(['upload', 'create', path]);
        uploads[h] = { id: u.id, name: basename(path), at: new Date().toISOString() };
        changed = true;
        console.log(`uploaded ${basename(path)} (free)`);
      }
      out.push(`${uploads[h].id}${role}`);
      continue;
    }
    out.push(a);
    key.push(a);
  }
  if (changed) { mkdirSync(home(), { recursive: true }); writeFileSync(uploadsPath(), JSON.stringify(uploads, null, 1)); }
  return { args: out, key };
}

// ---------------------------------------------------------------- results

/** Every result address in a job object, skipping thumbnails and the inputs echoed in params. */
function resultUrls(node, key = '') {
  if (!node || typeof node !== 'object') {
    return typeof node === 'string' && /^https?:\/\//.test(node) && /url/i.test(key) && !/^min_|thumb|preview|input|report/i.test(key) ? [node] : [];
  }
  return Object.entries(node).flatMap(([k, v]) => (k === 'params' ? [] : resultUrls(v, Array.isArray(node) ? key : k)));
}

async function download(url, file) {
  const res = await fetch(url).catch(() => null);
  if (!res || !res.ok) return false;
  writeFileSync(file, Buffer.from(await res.arrayBuffer()));
  return true;
}

/** Copy the cached files to --out. One file to a file name; several into a folder. */
function deliver(files, out) {
  if (!out || !files.length) return files;
  const asDir = files.length > 1 || out.endsWith('/') || out.endsWith('\\') || (existsSync(out) && statSync(out).isDirectory());
  const placed = files.map((f, i) => {
    const target = asDir ? join(out, basename(f)) : extname(out) ? out : `${out}${extname(f)}`;
    mkdirSync(dirname(resolve(target)), { recursive: true });
    copyFileSync(f, target);
    return target;
  });
  return placed;
}

function ledger(row) {
  mkdirSync(home(), { recursive: true });
  appendFileSync(ledgerPath(), `${JSON.stringify({ at: new Date().toISOString(), ...row })}\n`);
}

const keyOf = (o) => sha(JSON.stringify(o)).slice(0, 16);

/**
 * Create a job, then poll it ourselves with a deadline. `generate create --wait` once hung for
 * ten minutes before any job existed. The job id is saved the moment it exists, so a run that
 * stops early is resumed by running the same command again, never paid for twice.
 */
async function createAndPoll(id, flags, timeoutS, ctx = {}) {
  const pending = join(cacheDir(), `${id}.pending.json`);
  mkdirSync(cacheDir(), { recursive: true });
  let jobIds;
  if (existsSync(pending)) {
    jobIds = JSON.parse(readFileSync(pending, 'utf8')).jobs;
    console.log(`resuming job ${jobIds.join(', ')}. It was already paid for.`);
    ctx.resumed = true;
  } else {
    const created = await cliJson(['generate', 'create', ...flags]);
    const list = Array.isArray(created) ? created : created?.jobs || [created];
    jobIds = list.map((j) => (typeof j === 'string' ? j : j?.id || j?.job_id)).filter(Boolean);
    if (!jobIds.length) throw new HfError(`Higgsfield started the job but gave no job id:\n${JSON.stringify(created).slice(0, 300)}`);
    writeFileSync(pending, JSON.stringify({ at: new Date().toISOString(), jobs: jobIds }));
  }
  const deadline = Date.now() + timeoutS * 1000;
  const done = [];
  for (const jobId of jobIds) {
    for (let i = 0; ; i += 1) {
      const got = await cliJson(['generate', 'get', jobId]);
      const job = Array.isArray(got) ? got[0] : got;
      if (job.status === 'completed') { done.push(job); break; }
      if (/fail|error|cancel|nsfw|reject/i.test(job.status)) {
        unlinkSync(pending);
        throw new HfError(`Higgsfield job ${jobId} ended as ${job.status}.`);
      }
      if (Date.now() > deadline) {
        throw new HfError(`job ${jobId} is still ${job.status} after ${timeoutS} s. Run the same command again later: it picks the job up without paying again.`);
      }
      if (i % 6 === 0) console.error(`job ${jobId}: ${job.status}...`);
      await wait(5000);
    }
  }
  unlinkSync(pending);
  return done;
}
const show = (n) => (n === null || n === undefined ? 'unknown' : String(Math.round(n * 100) / 100));

// ---------------------------------------------------------------- the paid door

/**
 * One paid request: quote, guard, cache, run, measure, ledger.
 *   kind      ledger label
 *   key       what makes two requests the same
 *   quote     async () => credits, or null when Higgsfield cannot price it
 *   run       async () => job objects (or any JSON the CLI printed)
 *   request   what is shown on --dry
 */
async function paid({ kind, key, quote, run, request, g, cache = true }) {
  const id = keyOf({ kind, key });
  const recordPath = join(cacheDir(), `${id}.json`);
  const hit = cache && existsSync(recordPath) && !g.fresh;
  const est = hit ? 0 : await quote();

  console.log(`${kind}: ${hit ? 'already paid for, costs 0' : est === null ? 'Higgsfield gives no price for this' : `quote ${show(est)} credits (from Higgsfield, before running)`}` +
    `   cache ${id}`);

  if (g.dry) {
    if (g.max && est !== null && est > Number(g.max)) console.log(`would be refused: ${show(est)} is above --max ${g.max}`);
    console.log(`request: higgsfield ${request.map((a) => (/\s/.test(a) ? JSON.stringify(a) : a)).join(' ')}`);
    console.log('dry run. Nothing was generated and nothing was spent.');
    return;
  }
  if (g.fresh && (!g.why || g.why === true)) throw new HfError('--fresh pays again for a request already made. Say why with --why "...".', { code: 3 });
  if (g.max && est !== null && est > Number(g.max)) throw new HfError(`refused: the quote ${show(est)} is above --max ${g.max}. Nothing was spent.`, { code: 3 });
  if (hit) {
    const rec = JSON.parse(readFileSync(recordPath, 'utf8'));
    const files = rec.files.filter((f) => existsSync(f));
    for (const u of files.length ? [] : rec.urls) {
      const f = join(cacheDir(), `${id}-${basename(new URL(u).pathname)}`);
      if (await download(u, f)) files.push(f);
    }
    const placed = deliver(files, g.out);
    console.log(`cache hit, 0 credits. Paid on ${rec.at}.`);
    for (const p of placed) console.log(`  -> ${p}`);
    for (const u of rec.urls) console.log(`  ${u}`);
    return;
  }
  if (est === null && !g.yes) {
    throw new HfError(`${kind} cannot be priced in advance. Ask the user, then run it again with --yes.`, { code: 3 });
  }

  const release = await lock();
  const before = await balance();
  checkAccount(before);
  if (est !== null && before.credits - est < RESERVE) {
    throw new HfError(
      `refused: ${show(before.credits)} credits left, this costs ${show(est)}, and the reserve is ${RESERVE}.\n` +
      'Lower the reserve for this run with HF_RESERVE=<n> only if the user agrees. Nothing was spent.', { code: 3 });
  }
  if (est === null && before.credits <= RESERVE) {
    throw new HfError(`refused: ${show(before.credits)} credits left, at or under the reserve of ${RESERVE}. Nothing was spent.`, { code: 3 });
  }
  const baseline = (await transactions().catch(() => []))[0]?.created_at || null;

  // From here on money may be spent, so a failure is still measured and written down.
  let result = null;
  let failure = null;
  // A resumed job was charged on the earlier run, and that run's ledger row holds the cost.
  const ctx = { resumed: false };
  try { result = await run(id, ctx); } catch (err) { failure = err; }
  const m = await measure(before, baseline, est !== 0 && !ctx.resumed);
  if (ctx.resumed) Object.assign(m, { measured: 0, measured_by: 'resumed' });
  release();

  const urls = result ? [...new Set(resultUrls(result))] : [];
  const files = [];
  if (urls.length) mkdirSync(cacheDir(), { recursive: true });
  for (const u of urls) {
    const f = join(cacheDir(), `${id}-${basename(new URL(u).pathname)}`);
    if (await download(u, f)) files.push(f);
  }
  const jobs = (Array.isArray(result) ? result : result ? [result] : []).map((j) => j && (j.id || j.job_id)).filter(Boolean);
  if (result && cache) writeFileSync(recordPath, JSON.stringify({ at: new Date().toISOString(), kind, jobs, urls, files }, null, 1));
  const placed = deliver(files, g.out);

  ledger({
    kind,
    cache: id,
    quote: ctx.resumed ? 0 : est,
    measured: m.measured,
    measured_by: m.measured_by,
    spends: m.items,
    left: m.left,
    settled: m.measured !== null,
    ok: !failure,
    error: failure ? String(failure.message).slice(0, 300) : null,
    tag: typeof g.tag === 'string' ? g.tag : null,
    why: typeof g.why === 'string' ? g.why : null,
    out: placed.length ? placed : null,
    jobs,
    urls,
    request,
  });

  if (failure) {
    console.log(`failed. ${m.measured ? `It still cost ${show(m.measured)} credits.` : 'No spend was seen.'} ${show(m.left)} left.`);
    throw failure;
  }
  console.log(`done. measured ${show(m.measured)} credits${m.measured_by ? ` (from ${m.measured_by})` : ''}` +
    `${est !== null ? ` (quote ${show(est)})` : ''}, ${show(m.left)} left.`);
  for (const p of placed) console.log(`  -> ${p}`);
  if (!placed.length) for (const f of files) console.log(`  -> ${f}`);
  for (const u of urls) console.log(`  ${u}`);
  if (!urls.length && result) console.log(JSON.stringify(result, null, 1).slice(0, 2000));
  if (m.measured === null && est) console.log('note: the cost could not be measured yet. The ledger row says settled: false. Check with: node scripts/hf.mjs account');
  if (m.measured !== null && est && Math.abs(m.measured - est) > Math.max(1, est * 0.25)) {
    console.log('note: the measured cost is far from the quote. Another job on the same account at the same time also counts.');
  }
}

// ---------------------------------------------------------------- quotes

// Some jobs have no price endpoint (Virality Predictor said: "does not support alpha v2 cost
// estimation"). That is "no quote", which needs --yes, not an error. Bad parameters still are.
async function quoteOrNull(args) {
  try { return creditsOf(await cliJson(args)); } catch (err) {
    if (/does not support .*cost/i.test(err.message)) return null;
    throw err;
  }
}

const creditsOf = (j) => {
  if (typeof j === 'number') return j;
  if (!j || typeof j !== 'object') return null;
  for (const k of ['credits', 'cost', 'total_credits', 'price']) if (Number.isFinite(Number(j[k])) && j[k] !== null) return Number(j[k]);
  for (const v of Object.values(j)) { const n = creditsOf(v); if (n !== null) return n; }
  return null;
};

// photoshoot and marketplace cards plan their images first. --enhance-only returns the plan for
// free (measured: the balance did not move), and each planned image is priced on its own.
async function quotePlanned(base, rest) {
  const plan = await cliJson([...base, ...rest, '--enhance-only']);
  const prompts = plan.prompts || plan.items || [];
  if (!prompts.length) return null;
  let total = 0;
  for (const p of prompts) {
    const model = p.model || p.job_type || 'nano_banana_2';
    const extra = [];
    if (p.aspect_ratio) extra.push('--aspect_ratio', p.aspect_ratio);
    if (p.resolution) extra.push('--resolution', p.resolution);
    let c;
    try { c = await cliJson(['generate', 'cost', model, '--prompt', 'x', ...extra]); } catch {
      c = await cliJson(['generate', 'cost', model, '--prompt', 'x']);
    }
    total += creditsOf(c) || 0;
  }
  console.log(`plan: ${prompts.length} image(s): ${[...new Set(prompts.map((p) => p.model))].join(', ')}`);
  return total;
}

// ---------------------------------------------------------------- commands

const USAGE = `hf.mjs — Higgsfield generation with a credit guard. Wraps the higgsfield CLI.

Free:
  check                                   is the CLI installed and signed in
  account                                 plan, credits, the reserve, what can be spent now
  cost <model> [--param v]...             price a job without running it
  cost workflow <name> [--param v]...
  ledger                                  what has been spent, by kind and by tag
  run <higgsfield command...>             any free CLI command (lists, model get, presets,
                                          uploads, marketing-studio lists). Paid and outward
                                          commands are refused here.

Paid (quoted first):
  create <model> [--param v]...           image, video, audio or 3D job (waits for it)
  workflow <name> [--param v]...          a workflow job, such as reframe or draw_to_video
  photoshoot [product-photoshoot create flags]
  cards [marketplace-cards create flags]
  dtc [marketing-studio dtc-ads generate flags]

Outward or not undoable (needs --yes, ask the user first):
  act <higgsfield command...>             soul-id create, website create|deploy|publish|rename|
                                          contest|repo-access|secrets set|delete, workspace set|unset

Local files in any flag are uploaded once (free) and reused by id.

Every paid command also takes:
  --dry        show the quote and the request, run nothing
  --max N      refuse if the quote is above N credits
  --fresh      skip the cache and pay again (needs --why)
  --yes        allow a call Higgsfield cannot price
  --timeout S  for create: stop waiting after S seconds (default 900). Rerun to resume
  --tag NAME   group this call in the ledger
  --why "..."  one line on what this is for
  --out PATH   where to save the result (a file, or a folder for several)
  --prompt-file FILE   read --prompt from a file (keeps quotes and line breaks)

Cache and ledger: ${home()}   (HIGGSFIELD_HOME moves it)
Reserve: ${RESERVE} credits   (HF_RESERVE, or "reserve" in <home>/config.json)
Account: ${ACCOUNT || 'any'}   (HF_ACCOUNT, or "account" in <home>/config.json; others are refused)`;

const COMMANDS = {
  help() { console.log(USAGE); },

  async check() {
    const v = await exec(['version']).catch((e) => { throw e; });
    if (v.code !== 0) throw new HfError(explain(v.err || v.out));
    console.log(`CLI: ${v.out.trim().split('\n')[0]}`);
    const b = await balance();
    console.log(`signed in. plan ${b.plan}, ${show(b.credits)} credits.`);
  },

  async account() {
    const b = await balance();
    console.log(`plan ${b.plan}   credits ${show(b.credits)}`);
    if (ACCOUNT) {
      console.log(b.email && b.email.toLowerCase() !== ACCOUNT.toLowerCase()
        ? `WRONG ACCOUNT: signed in as ${b.email}, but this project spends from ${ACCOUNT}. Paid jobs are refused.`
        : `account ${ACCOUNT}, as this project requires`);
    }
    console.log(`reserve ${RESERVE}   so paid calls can spend up to ${show(Math.max(0, b.credits - RESERVE))} now`);
    const t = await transactions().catch(() => []);
    if (t.length) {
      console.log('recent:');
      for (const x of t.slice(0, 5)) console.log(`  ${x.created_at.slice(0, 16).replace('T', ' ')}  ${String(x.credits).padStart(7)}  ${x.display_name}`);
    }
    console.log(`cache and ledger: ${home()}`);
  },

  async cost(argv) {
    const { rest } = splitGuard(argv);
    if (!rest.length) throw new HfError('cost needs a model, or: cost workflow <name>');
    const j = await cliJson(['generate', 'cost', ...rest]);
    console.log(`quote: ${show(creditsOf(j))} credits. Nothing was spent.`);
  },

  async create(argv) {
    const { g, rest } = splitGuard(argv);
    if (!rest.length || rest[0].startsWith('-')) throw new HfError('create needs a model first. List them with: node scripts/hf.mjs run model list');
    const { args, key } = await prepare(rest, { upload: !g.dry });
    const flags = args;
    await paid({
      kind: `create:${rest[0]}`, key, g,
      request: ['generate', 'create', ...flags],
      quote: () => quoteOrNull(['generate', 'cost', ...flags]),
      run: (id, ctx) => createAndPoll(id, flags, Number(g.timeout || 900), ctx),
    });
  },

  async workflow(argv) {
    const { g, rest } = splitGuard(argv);
    if (!rest.length || rest[0].startsWith('-')) throw new HfError('workflow needs a workflow name. List them with: node scripts/hf.mjs run workflow list');
    const { args, key } = await prepare(rest, { upload: !g.dry });
    const flags = args;
    await paid({
      kind: `workflow:${rest[0]}`, key, g,
      request: ['generate', 'workflow', ...flags, '--wait'],
      quote: () => quoteOrNull(['generate', 'cost', 'workflow', ...flags]),
      run: () => cliJson(['generate', 'workflow', ...flags, '--wait'], { progress: true }),
    });
  },

  async photoshoot(argv) {
    const { g, rest } = splitGuard(argv);
    const { args, key } = await prepare(rest, { upload: !g.dry });
    const base = ['product-photoshoot', 'create'];
    await paid({
      kind: 'photoshoot', key, g, request: [...base, ...args],
      quote: () => quotePlanned(base, args),
      run: () => cliJson([...base, ...args], { progress: true }),
    });
  },

  async cards(argv) {
    const { g, rest } = splitGuard(argv);
    const { args, key } = await prepare(rest, { upload: !g.dry });
    const base = ['marketplace-cards', 'create'];
    await paid({
      kind: 'cards', key, g, request: [...base, ...args],
      quote: () => quotePlanned(base, args),
      run: () => cliJson([...base, ...args], { progress: true }),
    });
  },

  async dtc(argv) {
    const { g, rest } = splitGuard(argv);
    const { args, key } = await prepare(rest, { upload: !g.dry });
    const base = ['marketing-studio', 'dtc-ads', 'generate'];
    const flags = args;
    await paid({
      kind: 'dtc', key, g, request: [...base, ...flags, '--wait'],
      quote: () => quoteOrNull([...base, ...flags, '--cost-only']),
      run: () => cliJson([...base, ...flags, '--wait'], { progress: true }),
    });
  },

  async act(argv) {
    const { g, rest } = splitGuard(argv);
    if (!isAct(rest)) throw new HfError(`"${rest.join(' ')}" is not an outward action. Use run for free commands, or the paid commands.`);
    if (!g.yes) throw new HfError(`"higgsfield ${words(rest).join(' ')}" acts outside this machine or cannot be undone. Ask the user, then add --yes.`, { code: 3 });
    const { args, key } = await prepare(rest, { upload: true });
    await paid({
      kind: `act:${words(rest).join(' ')}`, key, g, cache: false, request: args,
      quote: async () => null,
      run: async () => {
        const r = await exec([...args, '--json'], { progress: true });
        if (r.code !== 0) throw new HfError(explain(r.err || r.out));
        try { return JSON.parse(r.out); } catch { return { output: r.out.trim() }; }
      },
    });
  },

  async run(argv) {
    if (!argv.length) throw new HfError('run needs a higgsfield command, for example: run model list --image');
    const [a, b] = words(argv);
    if (a === 'auth' && b === 'token') throw new HfError('Printing the sign-in token is refused. Nothing here needs it.', { code: 3 });
    const route = paidRoute(argv);
    if (route) throw new HfError(`That spends credits. Use: node scripts/hf.mjs ${route} ...  (it quotes first)`, { code: 3 });
    if (isAct(argv)) throw new HfError('That acts outside this machine or cannot be undone. Ask the user, then use: node scripts/hf.mjs act ... --yes', { code: 3 });
    const interactive = a === 'auth' && b === 'login';
    const r = await exec(argv, { interactive });
    if (!interactive) {
      if (r.code !== 0) throw new HfError(explain(r.err || r.out));
      process.stdout.write(r.out);
    }
  },

  ledger() {
    if (!existsSync(ledgerPath())) { console.log(`nothing spent yet (no ledger at ${ledgerPath()})`); return; }
    const rows = readFileSync(ledgerPath(), 'utf8').trim().split('\n').filter(Boolean).map((l) => JSON.parse(l));
    const group = (k) => rows.reduce((m, r) => {
      const name = (k === 'kind' ? r.kind : r[k]) || '(none)';
      m[name] ??= { calls: 0, quote: 0, measured: 0 };
      m[name].calls += 1;
      m[name].quote += r.quote || 0;
      m[name].measured += r.measured || 0;
      return m;
    }, {});
    for (const [title, k] of [['by kind', 'kind'], ['by tag', 'tag']]) {
      console.log(title);
      for (const [n, v] of Object.entries(group(k))) {
        console.log(`  ${n.padEnd(30)} ${String(v.calls).padStart(4)} calls   measured ${show(v.measured).padStart(8)}   quoted ${show(v.quote)}`);
      }
    }
    const measured = rows.reduce((s, r) => s + (r.measured || 0), 0);
    console.log(`total: ${show(measured)} credits measured over ${rows.length} paid calls`);
    const open = rows.filter((r) => r.measured === null).length;
    if (open) console.log(`${open} call(s) were never measured, so the total may be low`);
    console.log(`ledger: ${ledgerPath()}`);
  },
};

// pathToFileURL, not string concatenation: a Windows path like C:\... is not a valid URL.
// realpath first: started through a symlinked install, argv[1] is the link and import.meta.url
// the real file, and without it the script would exit having done nothing.
const isMain = process.argv[1] && import.meta.url === pathToFileURL(realpathSync(process.argv[1])).href;
if (isMain) {
  const [cmd = 'help', ...argv] = process.argv.slice(2);
  const handler = COMMANDS[cmd === '--help' || cmd === '-h' ? 'help' : cmd];
  if (!handler) {
    console.error(`unknown command "${cmd}"\n`);
    console.error(USAGE);
    process.exit(1);
  }
  try {
    await handler(argv);
  } catch (err) {
    console.error(err instanceof HfError ? err.message : `error: ${err.message}`);
    process.exit(err.code || 1);
  }
}
