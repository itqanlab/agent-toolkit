#!/usr/bin/env node
// nc.mjs — the Namecheap commands.
//
// The credential is read from the shared store and used in-process. It is never
// printed and never placed on a command line (see lib/transport.mjs for how).
//
// Three things about this API shape everything below:
//
//   1. There is no token, and no "which account is this" call. An account is a
//      username and an API key, and the local name given at setup is the only
//      label a user has. It is printed on everything that changes something.
//   2. DNS records are replaced as a whole. `setHosts` does not add a record; it
//      makes the list you send the entire list, and anything left out is deleted.
//      So every record edit here reads the current list, changes it in memory,
//      shows the difference, and only then sends all of it back.
//   3. Most domains do not have DNS at Namecheap at all. Anyone who put a domain
//      behind Cloudflare has records there, and Namecheap holds none. Asking for
//      records then fails, and the failure is the answer rather than a bug.

import { resolveTarget, takeTargetFlag } from '../lib/targets.mjs';
import { send, NamecheapError, publicIp } from '../lib/transport.mjs';
import { elements, first } from '../lib/xml.mjs';

export const SPEC = {
  provider: 'namecheap',
  label: 'Namecheap account',
  prefix: 'NAMECHEAP',
  flag: 'account',
  fields: { user: 'NAMECHEAP_USER', key: 'NAMECHEAP_KEY', relay: 'NAMECHEAP_RELAY' },
  optional: ['relay'],
};

let current = null;

export function useAccount(name) {
  const target = resolveTarget(SPEC, name);
  current = { name: target.name, user: target.fields.user, key: target.fields.key, relay: target.fields.relay || '' };
  return current;
}

export function account() {
  if (!current) useAccount('');
  return current;
}

/** One API call as the selected account. Returns the raw XML. */
export const api = (command, params) => send(command, params, account());

const flag = (args, name, fallback) => {
  const at = args.indexOf(`--${name}`);
  return at === -1 ? fallback : args[at + 1];
};

/** Arguments that are not flags or a flag's value. */
const positional = (args, valueFlags = []) => args.filter((a, i) =>
  !a.startsWith('--') && !valueFlags.some((f) => args[i - 1] === `--${f}`));

async function route() {
  const { relay } = account();
  const ip = await publicIp(relay);
  return relay ? `through the relay (${relay}), which Namecheap sees as ${ip}` : `directly from this machine, which Namecheap sees as ${ip}`;
}

// --- domains -----------------------------------------------------------------

/** Every domain on the account, following pages to the end. */
export async function listDomains() {
  const out = [];
  for (let page = 1; ; page += 1) {
    const xml = await api('namecheap.domains.getList', { PageSize: 100, Page: page });
    const rows = elements(xml, 'Domain').map((e) => e.attrs);
    out.push(...rows);
    const total = Number(first(xml, 'TotalItems')?.text || 0);
    if (!rows.length || out.length >= total) return out;
  }
}

/** Namecheap dates are MM/DD/YYYY. */
const toDate = (text) => {
  const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(text || '');
  return m ? new Date(Date.UTC(Number(m[3]), Number(m[1]) - 1, Number(m[2]))) : null;
};
const iso = (date) => (date ? date.toISOString().slice(0, 10) : '?');
const daysUntil = (date) => (date ? Math.ceil((date.getTime() - Date.now()) / 86_400_000) : null);

/**
 * The registered domain a name belongs to. Accepts `app.example.com` and finds
 * `example.com`, because the person asking is thinking about the site, not about
 * which part of it is registered. Longest match wins.
 *
 * A registered name is one label plus a public suffix, so SLD and TLD split at
 * the first dot — including for suffixes like co.uk, where the TLD is "co.uk".
 */
export async function findDomain(input) {
  const wanted = String(input || '').trim().toLowerCase().replace(/\.$/, '');
  if (!wanted) throw new Error('a domain name is needed');
  const all = await listDomains();
  const match = all
    .filter((d) => wanted === d.Name.toLowerCase() || wanted.endsWith(`.${d.Name.toLowerCase()}`))
    .sort((a, b) => b.Name.length - a.Name.length)[0];
  if (!match) {
    throw new NamecheapError(
      `Account "${account().name}" has no domain that "${wanted}" belongs to.\n` +
      `Domains here: ${all.map((d) => d.Name).join(', ') || '(none)'}`,
    );
  }
  const dot = match.Name.indexOf('.');
  return { name: match.Name, sld: match.Name.slice(0, dot), tld: match.Name.slice(dot + 1), entry: match, host: wanted };
}

// --- DNS records ---------------------------------------------------------------
// The record list is replaced as a whole, so the functions that change it are
// plain data-in, data-out and are exported for that reason.

export const RECORD_TYPES = ['A', 'AAAA', 'ALIAS', 'CAA', 'CNAME', 'MX', 'MXE', 'NS', 'TXT', 'URL', 'URL301', 'FRAME'];

/** `app.example.com` in `example.com` is "app"; the domain itself is "@". */
export const relativeName = (host, domain) => (host === domain ? '@' : host.slice(0, -(domain.length + 1)));

const sameSlot = (a, b) => a.name.toLowerCase() === b.name.toLowerCase() && a.type.toUpperCase() === b.type.toUpperCase();
const describe = (r) => `${r.type.padEnd(6)} ${r.name.padEnd(20)} -> ${r.address}${r.type === 'MX' ? `  (priority ${r.mxPref || 10})` : ''}`;

/**
 * Add a record. By default it replaces whatever already sits at that name and
 * type, which is what "point app at this server" means. `append` keeps the
 * others, for the cases that really do want several (MX, TXT).
 */
export function withRecord(hosts, record, { append = false } = {}) {
  const replaced = append ? [] : hosts.filter((h) => sameSlot(h, record));
  const kept = hosts.filter((h) => !replaced.includes(h) && !(append && sameSlot(h, record) && h.address === record.address));
  return { hosts: [...kept, record], removed: replaced, added: record };
}

/** Remove records by name and type, and by value too when one is given. */
export function withoutRecords(hosts, { name, type, address }) {
  const removed = hosts.filter((h) => sameSlot(h, { name, type }) && (!address || h.address === address));
  return { hosts: hosts.filter((h) => !removed.includes(h)), removed };
}

/** The numbered parameters `setHosts` expects: HostName1, RecordType1, Address1, ... */
export function setHostsParams(hosts, emailType) {
  const params = {};
  if (emailType) params.EmailType = emailType;
  hosts.forEach((h, i) => {
    const n = i + 1;
    params[`HostName${n}`] = h.name;
    params[`RecordType${n}`] = h.type;
    params[`Address${n}`] = h.address;
    if (h.type.toUpperCase() === 'MX') params[`MXPref${n}`] = h.mxPref || 10;
    if (h.ttl) params[`TTL${n}`] = h.ttl;
  });
  return params;
}

async function readHosts(domain) {
  const xml = await api('namecheap.domains.dns.getHosts', { SLD: domain.sld, TLD: domain.tld });
  const result = first(xml, 'DomainDNSGetHostsResult');
  return {
    emailType: result?.attrs.EmailType || '',
    hosts: elements(xml, 'host').map((h) => ({
      name: h.attrs.Name, type: h.attrs.Type, address: h.attrs.Address, mxPref: h.attrs.MXPref, ttl: h.attrs.TTL,
    })),
  };
}

/**
 * Send the whole list, then read it back. The read-back is not ceremony: this
 * call deletes whatever it is not given, so "it said OK" is not enough to
 * report success.
 */
async function writeHosts(domain, hosts, emailType) {
  await api('namecheap.domains.dns.setHosts', { SLD: domain.sld, TLD: domain.tld, ...setHostsParams(hosts, emailType) });
  const after = await readHosts(domain);
  if (after.hosts.length !== hosts.length) {
    throw new NamecheapError(
      `Namecheap accepted the change to ${domain.name} but now holds ${after.hosts.length} record(s), not the ${hosts.length} that were sent.\n` +
      'Look at what is there before doing anything else:  node scripts/nc.mjs dns ' + domain.name,
    );
  }
  return after;
}

// --- commands ------------------------------------------------------------------

const money = (amount, currency) => (amount === undefined || amount === '' ? '' : `${currency === 'USD' || !currency ? '$' : `${currency} `}${Number(amount).toFixed(2)}`);

async function balance() {
  const xml = await api('namecheap.users.getBalances', {});
  const a = first(xml, 'UserGetBalancesResult')?.attrs || {};
  return { amount: a.AvailableBalance, currency: a.Currency, autoRenewNeeds: a.FundsRequiredForAutoRenew };
}

const COMMANDS = {
  async whoami() {
    const [bal, domains] = await Promise.all([balance(), listDomains()]);
    console.log(`account:  ${account().name}   (the name is yours — Namecheap does not label credentials)`);
    console.log(`user:     ${account().user}`);
    console.log(`route:    ${await route()}`);
    console.log(`domains:  ${domains.length}`);
    console.log(`balance:  ${money(bal.amount, bal.currency)}`);
  },

  async balance() {
    const bal = await balance();
    console.log(`${money(bal.amount, bal.currency)} available on account "${account().name}"`);
    if (Number(bal.autoRenewNeeds) > 0) console.log(`Auto-renewing domains will need ${money(bal.autoRenewNeeds, bal.currency)} more than that.`);
  },

  async domains(args) {
    const within = flag(args, 'expiring');
    const all = await listDomains();
    const rows = all
      .map((d) => ({ ...d, expires: toDate(d.Expires) }))
      .sort((a, b) => (a.expires?.getTime() ?? 0) - (b.expires?.getTime() ?? 0))
      .filter((d) => !within || daysUntil(d.expires) <= Number(within));

    if (!rows.length) return console.log(within ? `nothing on "${account().name}" expires within ${within} days` : `no domains on "${account().name}"`);
    console.log(`account "${account().name}" — ${rows.length}${within ? ` expiring within ${within} days, of ${all.length}` : ''} domain(s)\n`);
    for (const d of rows) {
      const left = daysUntil(d.expires);
      const when = d.IsExpired === 'true' ? 'EXPIRED' : `${left} days`;
      console.log(
        `${d.Name.padEnd(30)} ${iso(d.expires)} ${`(${when})`.padEnd(13)} ` +
        `auto-renew ${d.AutoRenew === 'true' ? 'on ' : 'OFF'}   DNS ${d.IsOurDNS === 'true' ? 'here    ' : 'elsewhere'}   ${d.IsLocked === 'true' ? 'locked' : ''}`,
      );
    }
    const atRisk = rows.filter((d) => d.AutoRenew !== 'true' && daysUntil(d.expires) <= 60);
    if (atRisk.length) {
      console.log(`\n! ${atRisk.length} expire within 60 days with auto-renew off, so Namecheap will not renew them on its own:`);
      for (const d of atRisk) console.log(`    ${d.Name}  (${daysUntil(d.expires)} days)`);
      console.log('  What renewing costs:  node scripts/nc.mjs price <tld>');
    }
  },

  async domain([input]) {
    if (!input) throw new Error('usage: domain <name>');
    const d = await findDomain(input);
    const xml = await api('namecheap.domains.getInfo', { DomainName: d.name });
    const details = first(xml, 'DomainDetails')?.raw || '';
    const dns = first(xml, 'DnsDetails');
    const guard = first(xml, 'Whoisguard');
    const left = daysUntil(toDate(d.entry.Expires));

    console.log(`${d.name}   on account "${account().name}"`);
    console.log(`  registered:  ${iso(toDate(first(details, 'CreatedDate')?.text))}`);
    console.log(`  expires:     ${iso(toDate(d.entry.Expires))} (${left} days)`);
    console.log(`  auto-renew:  ${d.entry.AutoRenew === 'true' ? 'on' : 'OFF'}`);
    console.log(`  locked:      ${d.entry.IsLocked === 'true' ? 'yes — cannot be transferred away' : 'no'}`);
    console.log(`  privacy:     ${guard?.attrs.Enabled?.toLowerCase() === 'true' ? 'on (contact details hidden)' : 'off'}`);
    console.log(`  DNS:         ${dns?.attrs.IsUsingOurDNS === 'true' ? "Namecheap's own — records are editable here" : 'elsewhere — records live wherever these point'}`);
    for (const ns of elements(dns?.raw || '', 'Nameserver')) console.log(`               ${ns.text}`);
    if (dns?.attrs.EmailType) console.log(`  email:       ${dns.attrs.EmailType}`);
  },

  async nameservers([input]) {
    if (!input) throw new Error('usage: nameservers <domain>');
    const d = await findDomain(input);
    const xml = await api('namecheap.domains.dns.getList', { SLD: d.sld, TLD: d.tld });
    const result = first(xml, 'DomainDNSGetListResult');
    console.log(`${d.name}   ${result?.attrs.IsUsingOurDNS === 'true' ? "Namecheap's own nameservers" : 'custom nameservers'}`);
    for (const ns of elements(result?.raw || '', 'Nameserver')) console.log(`  ${ns.text}`);
  },

  async 'nameservers-set'(args) {
    const [input, ...servers] = positional(args);
    if (!input || servers.length < 2) throw new Error('usage: nameservers-set <domain> <ns1> <ns2> [ns3...] --yes');
    const d = await findDomain(input);
    const now = elements((await api('namecheap.domains.dns.getList', { SLD: d.sld, TLD: d.tld })), 'Nameserver').map((n) => n.text);

    console.log(`${d.name}  (account "${account().name}")`);
    console.log(`  now:    ${now.join(', ') || '(none)'}`);
    console.log(`  change: ${servers.join(', ')}`);
    if (!args.includes('--yes')) {
      console.log('\nOnce these change, the domain answers from the new servers only. If they do not already hold');
      console.log('its records, the site and its email stop resolving until they do. Re-run with --yes to confirm.');
      process.exitCode = 1;
      return;
    }
    await api('namecheap.domains.dns.setCustom', { SLD: d.sld, TLD: d.tld, Nameservers: servers.join(',') });
    const after = elements((await api('namecheap.domains.dns.getList', { SLD: d.sld, TLD: d.tld })), 'Nameserver').map((n) => n.text);
    console.log(`\n${d.name} now uses: ${after.join(', ')}`);
    console.log('Namecheap holds the change straight away; resolvers around the world can take up to a day to follow.');
  },

  async 'nameservers-default'(args) {
    const [input] = positional(args);
    if (!input) throw new Error('usage: nameservers-default <domain> --yes');
    const d = await findDomain(input);
    if (!args.includes('--yes')) {
      console.log(`This hands DNS for ${d.name} back to Namecheap's own nameservers (account "${account().name}").`);
      console.log('Records kept at the current nameservers stop being used. Check what Namecheap holds after with:');
      console.log(`  node scripts/nc.mjs dns ${d.name}\n\nRe-run with --yes to confirm.`);
      process.exitCode = 1;
      return;
    }
    await api('namecheap.domains.dns.setDefault', { SLD: d.sld, TLD: d.tld });
    console.log(`${d.name} now uses Namecheap's own nameservers.`);
  },

  async check(args) {
    const names = positional(args);
    if (!names.length) throw new Error('usage: check <domain> [<domain> ...]');
    const xml = await api('namecheap.domains.check', { DomainList: names.join(',') });
    for (const r of elements(xml, 'DomainCheckResult')) {
      const a = r.attrs;
      const premium = a.IsPremiumName === 'true' ? `   PREMIUM — registration ${a.PremiumRegistrationPrice}, a premium name costs far more than a normal one` : '';
      console.log(`${a.Domain.padEnd(32)} ${a.Available === 'true' ? 'available' : 'taken'}${premium}`);
    }
  },

  async price(args) {
    const tlds = positional(args).map((t) => t.replace(/^\./, '').toLowerCase());
    if (!tlds.length) throw new Error('usage: price <tld> [<tld> ...]   e.g. price com io');
    for (const tld of tlds) {
      const found = {};
      for (const action of ['REGISTER', 'RENEW']) {
        const xml = await api('namecheap.users.getPricing', {
          ProductType: 'DOMAIN', ProductCategory: 'DOMAINS', ActionName: action, ProductName: tld.toUpperCase(),
        });
        const oneYear = elements(xml, 'Price').map((p) => p.attrs).find((p) => p.Duration === '1');
        if (oneYear) found[action] = oneYear;
      }
      if (!found.REGISTER && !found.RENEW) {
        console.log(`.${tld.padEnd(10)} no price found — Namecheap may not sell it, or the ending is spelled differently`);
        continue;
      }
      const fmt = (p) => (p ? `${money(p.YourPrice || p.Price, p.Currency)}${Number(p.AdditionalCost) ? ` (+${money(p.AdditionalCost, p.Currency)} fee)` : ''}` : 'n/a');
      console.log(`.${tld.padEnd(10)} register ${fmt(found.REGISTER).padEnd(22)} renew ${fmt(found.RENEW)}   per year`);
    }
  },

  async dns([input]) {
    if (!input) throw new Error('usage: dns <domain>');
    const d = await findDomain(input);
    const { hosts, emailType } = await readHosts(d);
    if (!hosts.length) return console.log(`${d.name} has no DNS records at Namecheap`);
    console.log(`${d.name} — ${hosts.length} record(s) at Namecheap${emailType ? `   (email: ${emailType})` : ''}\n`);
    for (const h of hosts) console.log(`${h.type.padEnd(7)} ${h.name.padEnd(22)} ${h.address}${h.type === 'MX' ? `   priority ${h.mxPref}` : ''}   ttl ${h.ttl}`);
  },

  async 'dns-add'(args) {
    const [hostname, type, value] = positional(args, ['ttl', 'priority']);
    if (!hostname || !type || !value) throw new Error('usage: dns-add <hostname> <type> <value> [--ttl 1800] [--priority 10] [--append] --yes');
    if (!RECORD_TYPES.includes(type.toUpperCase())) throw new Error(`"${type}" is not a record type Namecheap accepts. It takes: ${RECORD_TYPES.join(', ')}`);

    const d = await findDomain(hostname);
    const { hosts, emailType } = await readHosts(d);
    const record = {
      name: relativeName(d.host, d.name), type: type.toUpperCase(), address: value,
      ttl: flag(args, 'ttl', ''), mxPref: flag(args, 'priority', ''),
    };
    const plan = withRecord(hosts, record, { append: args.includes('--append') });

    console.log(`${d.name}  (account "${account().name}")\n`);
    for (const r of plan.removed) console.log(`  - ${describe(r)}`);
    console.log(`  + ${describe(record)}`);
    console.log(`\nNamecheap replaces the whole record list on every change. This sends ${plan.hosts.length} record(s): ` +
      `${hosts.length - plan.removed.length} unchanged, ${plan.removed.length ? 'one replaced' : 'one new'}.`);

    if (!args.includes('--yes')) {
      console.log('\nNothing has been changed. Re-run with --yes to confirm.');
      process.exitCode = 1;
      return;
    }
    await writeHosts(d, plan.hosts, emailType);
    console.log(`\ndone — ${d.name} now has ${plan.hosts.length} record(s).`);
  },

  async 'dns-remove'(args) {
    const [hostname] = positional(args, ['type', 'value']);
    const type = flag(args, 'type');
    if (!hostname || !type) throw new Error('usage: dns-remove <hostname> --type A [--value 1.2.3.4] --yes');

    const d = await findDomain(hostname);
    const { hosts, emailType } = await readHosts(d);
    const plan = withoutRecords(hosts, { name: relativeName(d.host, d.name), type: type.toUpperCase(), address: flag(args, 'value', '') });

    if (!plan.removed.length) return console.log(`no ${type.toUpperCase()} record for ${d.host} at Namecheap`);
    console.log(`${d.name}  (account "${account().name}")\n`);
    for (const r of plan.removed) console.log(`  - ${describe(r)}`);
    console.log(`\nThis leaves ${plan.hosts.length} record(s) and deletes ${plan.removed.length}.`);

    if (!plan.hosts.length) {
      console.log('\nThat would leave the domain with no records at all. Refusing — remove it in the Namecheap dashboard if that is really the aim.');
      process.exitCode = 1;
      return;
    }
    if (!args.includes('--yes')) {
      console.log('\nNothing has been changed. Re-run with --yes to confirm.');
      process.exitCode = 1;
      return;
    }
    await writeHosts(d, plan.hosts, emailType);
    console.log(`\ndone — ${d.name} now has ${plan.hosts.length} record(s).`);
  },

  /**
   * Any other Namecheap command. Things that change or spend are held back until
   * --yes, and `setHosts` is not reachable this way at all: sent by hand it wipes
   * every record it is not given, which is exactly what dns-add exists to prevent.
   */
  async call(args) {
    const [command, ...rest] = positional(args.filter((a) => a !== '--yes'));
    if (!command) throw new Error('usage: call <namecheap.command.name> [Key=value ...] [--yes]');
    if (/\.dns\.sethosts$/i.test(command)) {
      throw new Error('setHosts replaces every record on the domain. Use dns-add and dns-remove, which read the list first and put it back whole.');
    }
    const changes = /\.(set\w*|create|renew|reactivate|transfer\w*|delete|update\w*|register|push)$/i.test(command);
    if (changes && !args.includes('--yes')) {
      console.log(`${command} looks like it changes something or spends money, on account "${account().name}".`);
      console.log('Re-run with --yes once that is confirmed.');
      process.exitCode = 1;
      return;
    }
    const params = Object.fromEntries(rest.filter((p) => p.includes('=')).map((p) => [p.slice(0, p.indexOf('=')), p.slice(p.indexOf('=') + 1)]));
    console.log((await api(command, params)).trim());
  },
};

// --- command line --------------------------------------------------------------

const isMain = process.argv[1]?.endsWith('nc.mjs');
if (isMain) {
  const { name: accountName, args: argv } = takeTargetFlag(process.argv.slice(2), SPEC);
  const [command, ...args] = argv;
  const handler = COMMANDS[command];
  if (!handler) {
    console.error(`usage: nc.mjs [--account <name>] <${Object.keys(COMMANDS).join('|')}> [args]`);
    process.exit(2);
  }
  try {
    useAccount(accountName);
    await handler(args);
  } catch (err) {
    console.error(err instanceof NamecheapError ? err.message : `error: ${err.message}`);
    process.exit(1);
  }
}
