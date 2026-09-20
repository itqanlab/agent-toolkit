// transport.mjs — getting a request to Namecheap and an answer back.
//
// Namecheap has no bearer token. A call carries a username, an API key and the
// address it claims to come from, and Namecheap refuses it unless that address is
// on a list the account owner keeps by hand in the dashboard. Nothing in the API
// edits that list. So the real question on every machine is "which address will
// Namecheap see?", and there are two honest answers:
//
//   direct  this machine's own public address. Fine on a fixed connection, and
//           a chore on a home or mobile one, where the address changes and the
//           dashboard has to be edited each time.
//   relay   an SSH host whose address is whitelisted. The request is made from
//           there, so the address never changes. This is what most people with a
//           server already have, and it is the only thing that works from a laptop
//           that moves.
//
// The key never appears in a command line, on either route. Locally it goes in
// the request body. Through a relay it goes down ssh's stdin into curl's config
// reader, because an argument is visible to every user on the remote machine in
// its process list and to anything that logs commands.

import { spawn } from 'node:child_process';
import { homedir } from 'node:os';
import { parseResponse } from './xml.mjs';

const ENDPOINT = 'https://api.namecheap.com/xml.response';
const USER_AGENT = 'itqan-agent-toolkit/1.0 (+https://github.com/itqanlab/agent-toolkit)';
const IP_SOURCES = ['https://api.ipify.org', 'https://ipv4.icanhazip.com', 'https://ifconfig.me/ip'];
const IPV4 = /^\d{1,3}(\.\d{1,3}){3}$/;

export class NamecheapError extends Error {
  constructor(message, { code, ip } = {}) {
    super(message);
    this.name = 'NamecheapError';
    this.code = code;
    this.ip = ip;
  }
}

// --- the relay ---------------------------------------------------------------

/**
 * `-i ~/.ssh/key root@203.0.113.5` to an argument list for ssh. Split on spaces
 * (double quotes keep a path with a space in it together), with a leading `~`
 * expanded, because ssh does not do that for itself and a saved setting cannot
 * rely on a shell being there to do it.
 *
 * This is the user's own setting in their own credential file, so it is trusted
 * to hold whatever ssh options they need. It is never built from anything else.
 */
export function relayArgs(relay) {
  return [...String(relay).trim().matchAll(/"([^"]*)"|(\S+)/g)]
    .map((m) => m[1] ?? m[2])
    .map((part) => (part === '~' || part.startsWith('~/') ? homedir() + part.slice(1) : part));
}

/** Run a fixed command on the relay, optionally feeding it stdin. */
function onRelay(relay, remoteCommand, stdin = '') {
  const args = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', ...relayArgs(relay), remoteCommand];
  return new Promise((resolve, reject) => {
    let child;
    try {
      child = spawn('ssh', args, { stdio: ['pipe', 'pipe', 'pipe'] });
    } catch (err) {
      reject(new NamecheapError(`Could not start ssh (${err.message}). The relay needs an ssh client installed.`));
      return;
    }
    let out = '';
    let err = '';
    const timer = setTimeout(() => child.kill(), 45_000);
    child.stdout.on('data', (d) => { out += d; });
    child.stderr.on('data', (d) => { err += d; });
    child.on('error', (e) => {
      clearTimeout(timer);
      reject(new NamecheapError(
        e.code === 'ENOENT'
          ? 'ssh is not installed on this machine, so the relay cannot be used.'
          : `Could not start ssh: ${e.message}`,
      ));
    });
    child.on('close', (status) => {
      clearTimeout(timer);
      if (status === 0) return resolve(out);
      reject(new NamecheapError(
        `The relay did not answer (ssh exited ${status}).\n${err.trim().split('\n').slice(-3).join('\n')}\n\n` +
        'Check that this works on its own, with no password prompt:\n' +
        `  ssh ${args.slice(4, -1).join(' ')} true`,
      ));
    });
    child.stdin.on('error', () => {}); // ssh can close before reading; the exit status says why
    child.stdin.end(stdin);
  });
}

// --- the address Namecheap sees ---------------------------------------------

const seen = new Map();

/** The public IPv4 address a request will come from, on the chosen route. */
export async function publicIp(relay = '') {
  const cacheKey = relay || '(direct)';
  if (seen.has(cacheKey)) return seen.get(cacheKey);

  let ip = '';
  if (relay) {
    ip = (await onRelay(relay, 'curl -s -m 8 https://api.ipify.org')).trim();
  } else {
    for (const source of IP_SOURCES) {
      try {
        const response = await fetch(source, { headers: { 'User-Agent': USER_AGENT }, signal: AbortSignal.timeout(8000) });
        const text = (await response.text()).trim();
        if (IPV4.test(text)) { ip = text; break; }
      } catch { /* try the next source */ }
    }
  }
  if (!IPV4.test(ip)) {
    throw new NamecheapError(
      'Could not work out which public address Namecheap will see. It needs an IPv4 address, ' +
      `and ${relay ? 'the relay' : 'this machine'} did not return one. Check the internet connection.`,
    );
  }
  seen.set(cacheKey, ip);
  return ip;
}

// --- sending -----------------------------------------------------------------

async function viaRelay(relay, body) {
  // curl reads this as a config file: `data` makes it a POST and `url` says where.
  // The body is percent-encoded, so it holds no quote or backslash to escape.
  const config = `url = "${ENDPOINT}"\ndata = "${body}"\n`;
  return onRelay(relay, 'curl -sS -m 30 -K -', config);
}

async function viaDirect(body) {
  let lastError;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      const response = await fetch(ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'User-Agent': USER_AGENT },
        body,
        signal: AbortSignal.timeout(30_000),
      });
      return await response.text();
    } catch (err) {
      lastError = err;
      await new Promise((r) => setTimeout(r, attempt * 500));
    }
  }
  throw new NamecheapError(`Could not reach Namecheap (${lastError?.message}). Check the internet connection and try again.`);
}

/**
 * One call. Resolves with the raw XML when Namecheap says OK, and throws a
 * NamecheapError written for a person when it does not.
 *
 * `account` is `{ name, user, key, relay }` — the name is only for messages.
 */
export async function send(command, params, account) {
  const ip = await publicIp(account.relay);
  const body = new URLSearchParams({
    ApiUser: account.user,
    ApiKey: account.key,
    UserName: account.user,
    ClientIp: ip,
    Command: command,
  });
  for (const [k, v] of Object.entries(params || {})) {
    if (v !== undefined && v !== null && v !== '') body.set(k, String(v));
  }

  const xml = account.relay ? await viaRelay(account.relay, body.toString()) : await viaDirect(body.toString());
  const parsed = parseResponse(xml);

  if (!parsed) {
    // Never echo more than the start of it, and never the key.
    const snippet = xml.replaceAll(account.key, '<hidden>').replace(/\s+/g, ' ').trim().slice(0, 160);
    throw new NamecheapError(`Namecheap sent back something that is not an API answer: ${snippet || '(nothing)'}`);
  }
  if (!parsed.ok) {
    const first = parsed.errors[0] || { code: '', message: 'Namecheap rejected the request' };
    throw new NamecheapError(explain(first, { account, ip }), { code: first.code, ip });
  }
  return xml;
}

// --- error messages ----------------------------------------------------------

/**
 * Namecheap's errors, rewritten for someone who has never seen a number like
 * 1011150. Only codes that have actually come back from the live API are given
 * their own wording; the rest keep Namecheap's text and its number, which is
 * more useful than a guess presented as an explanation.
 */
export function explain({ code, message }, { account, ip }) {
  const who = `(account "${account.name}")`;
  switch (String(code)) {
    case '1011150':
      return (
        `Namecheap refused ${who}: it does not accept requests from ${ip}.\n\n` +
        'Namecheap only answers addresses on a list you keep in its dashboard, and this one is not on it.\n' +
        (account.relay
          ? `The address belongs to the relay (${account.relay}). Add ${ip} to the list:\n`
          : `That is this machine's public address. If it changes (home or mobile internet usually does),\n` +
            'this will keep breaking; a relay through a server with a fixed address avoids it. To add it:\n') +
        '  Namecheap dashboard → Profile → Tools → Namecheap API Access → Whitelisted IPs → add ' + ip
      );
    case '1011102':
      return (
        `Namecheap rejected the key ${who}: "${message}".\n` +
        'Either the key was pasted wrongly, or API access is switched off for the account.\n' +
        'Check it is on (Profile → Tools → Namecheap API Access), then paste the key again:\n' +
        `  node scripts/setup.mjs add ${account.name} --force`
      );
    case '2019166':
      return `This Namecheap account has no such domain ${who}. List what it does have with:  node scripts/nc.mjs domains`;
    case '2030288':
      return (
        'That domain does not use Namecheap\'s own nameservers, so Namecheap holds no records for it.\n' +
        'Its DNS lives wherever its nameservers point. See where:  node scripts/nc.mjs nameservers <domain>'
      );
    default:
      return `${message || 'Namecheap rejected the request'} (Namecheap error ${code || '?'}) ${who}`;
  }
}

/**
 * Check credentials without needing a saved account: used by setup before
 * anything is written. Never throws; says what is wrong instead.
 */
export async function probe(account) {
  try {
    const xml = await send('namecheap.users.getBalances', {}, account);
    const balance = /<UserGetBalancesResult\b([^>]*)\/?>/i.exec(xml)?.[1] || '';
    const amount = /AvailableBalance="([^"]*)"/.exec(balance)?.[1];
    const currency = /Currency="([^"]*)"/.exec(balance)?.[1] || '';
    return { ok: true, ip: await publicIp(account.relay), balance: amount === undefined ? '' : `${amount} ${currency}`.trim() };
  } catch (err) {
    return { ok: false, why: err.message, code: err.code, ip: err.ip };
  }
}
