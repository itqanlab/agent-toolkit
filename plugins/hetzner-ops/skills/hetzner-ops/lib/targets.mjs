#!/usr/bin/env node
// targets.mjs — several named accounts in one credential file.
//
// The shared store holds one file per provider. Some providers, though, are not
// one account: a Hetzner token belongs to a single project, and a Dokploy key to
// a single installation. People routinely have several, and the expensive
// mistake is not "which command" but "which one did that just run against".
//
// So a target is named locally, every key is suffixed with that name, and one of
// them is the default:
//
//     HETZNER_DEFAULT=itqanlab
//     HETZNER_TOKEN_ITQANLAB=...
//     HETZNER_TOKEN_CLIENT_A=...
//
// The name is ours, not the provider's. Neither provider will tell you what the
// credential you are holding actually points at — a Hetzner token does not name
// its project — so the local label is the only thing standing between the user
// and a change made in the wrong place. It gets printed on every write.

import { readSecrets, writeSecrets, providerPath } from './store.mjs';

/**
 * A display name to the fragment used in key names. Deliberately lossy: "Client
 * A" and "client-a" become the same target, because a user who types the second
 * having created the first means the same one, and silently creating a duplicate
 * would be worse than being strict.
 */
export function slug(name) {
  const out = String(name || '').trim().toUpperCase().replace(/[^A-Z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  if (!out) throw new Error(`"${name}" cannot be used as a name — it needs at least one letter or digit`);
  return out;
}

/** Names are stored as typed, so they can be printed back the way they were. */
const NAME_KEY = (spec, s) => `${spec.prefix}_NAME_${s}`;
const DEFAULT_KEY = (spec) => `${spec.prefix}_DEFAULT`;
const fieldKey = (spec, field, s) => `${spec.fields[field]}_${s}`;

const isSet = (value) => Boolean(value && !/^(<|paste|your[-_])/i.test(value));

/**
 * Every target in the file, whether complete or half-finished. A half-finished
 * one is normal: setup writes the empty keys, then waits for the user to paste.
 */
export function listTargets(spec) {
  const secrets = readSecrets(spec.provider);
  const names = new Map();

  for (const [key, value] of Object.entries(secrets)) {
    for (const [field, prefix] of Object.entries(spec.fields)) {
      const match = key.startsWith(`${prefix}_`) && key.slice(prefix.length + 1);
      if (!match) continue;
      const entry = names.get(match) || { slug: match, fields: {} };
      entry.fields[field] = value;
      names.set(match, entry);
    }
  }

  const fallbackDefault = secrets[DEFAULT_KEY(spec)];
  return [...names.values()]
    .map((entry) => ({
      ...entry,
      label: secrets[NAME_KEY(spec, entry.slug)] || '',
      name: secrets[NAME_KEY(spec, entry.slug)] || entry.slug.toLowerCase().replace(/_/g, '-'),
      complete: Object.keys(spec.fields).every((field) => isSet(entry.fields[field])),
      isDefault: fallbackDefault ? slug(fallbackDefault) === entry.slug : false,
    }))
    // Removing a target blanks its keys rather than rewriting the file, so the
    // empty lines linger. A target with no name and nothing in any field is one
    // of those ghosts, not something waiting to be filled in.
    .filter((entry) => entry.label || Object.values(entry.fields).some((v) => v && v.trim()))
    .sort((a, b) => a.name.localeCompare(b.name));
}

export function defaultTargetName(spec) {
  return readSecrets(spec.provider)[DEFAULT_KEY(spec)] || '';
}

/**
 * Work out which target a command should act on.
 *
 * Order: what was asked for, then the saved default, then the only one there is.
 * There is deliberately no "just pick the first" — with two targets configured
 * and no default set, guessing is how a change lands on the wrong account.
 */
export function resolveTarget(spec, requested) {
  const targets = listTargets(spec);
  const usable = targets.filter((t) => t.complete);

  if (!targets.length) {
    throw new Error(
      `No ${spec.label} is connected yet. Set one up first:\n` +
      `  node scripts/setup.mjs add <a-name-for-it>`,
    );
  }

  if (requested) {
    const wanted = slug(requested);
    const match = targets.find((t) => t.slug === wanted);
    if (!match) {
      throw new Error(
        `There is no ${spec.label} called "${requested}".\n` +
        `Configured: ${targets.map((t) => t.name).join(', ')}`,
      );
    }
    if (!match.complete) throw new Error(incomplete(spec, match));
    return match;
  }

  const saved = defaultTargetName(spec);
  if (saved) {
    const match = targets.find((t) => t.slug === slug(saved));
    if (match?.complete) return match;
  }

  if (usable.length === 1) return usable[0];

  if (!usable.length) throw new Error(incomplete(spec, targets[0]));

  throw new Error(
    `More than one ${spec.label} is configured and none is the default, so this would be a guess.\n` +
    `Configured: ${usable.map((t) => t.name).join(', ')}\n\n` +
    `Pick one for this command with  --${spec.flag} <name>,\n` +
    `or make one the default with    node scripts/setup.mjs use <name>`,
  );
}

function incomplete(spec, target) {
  const missing = Object.entries(spec.fields)
    .filter(([field]) => !isSet(target.fields[field]))
    .map(([, prefix]) => `${prefix}_${target.slug}`);
  return (
    `"${target.name}" is not finished — nothing has been pasted in yet.\n\n` +
    `Open this file and fill in:  ${missing.join(', ')}\n` +
    `  ${providerPath(spec.provider)}\n\n` +
    `Then run:  node scripts/setup.mjs verify ${target.name}`
  );
}

/** Create (or top up) the keys for a target, leaving values for the user. */
export function scaffoldTarget(spec, name, values = {}) {
  const s = slug(name);
  const existing = readSecrets(spec.provider);
  const updates = { [NAME_KEY(spec, s)]: name };

  for (const field of Object.keys(spec.fields)) {
    const key = fieldKey(spec, field, s);
    if (values[field] !== undefined) updates[key] = values[field];
    else if (!(key in existing)) updates[key] = '';
  }

  // First one in becomes the default, so a single-account user never meets the
  // concept at all.
  if (!existing[DEFAULT_KEY(spec)]) updates[DEFAULT_KEY(spec)] = name;

  writeSecrets(spec.provider, updates);
  return { slug: s, keys: Object.fromEntries(Object.keys(spec.fields).map((f) => [f, fieldKey(spec, f, s)])) };
}

export function setDefault(spec, name) {
  const target = listTargets(spec).find((t) => t.slug === slug(name));
  if (!target) throw new Error(`There is no ${spec.label} called "${name}".`);
  writeSecrets(spec.provider, { [DEFAULT_KEY(spec)]: target.name });
  return target;
}

/**
 * Forget a target. This blanks the values rather than rewriting the file, so a
 * stray comment the user added stays where they put it. The credential is gone
 * from disk either way — but it still exists at the provider, so the caller is
 * expected to say so.
 */
export function forgetTarget(spec, name) {
  const target = listTargets(spec).find((t) => t.slug === slug(name));
  if (!target) throw new Error(`There is no ${spec.label} called "${name}".`);

  const updates = Object.fromEntries(Object.keys(spec.fields).map((f) => [fieldKey(spec, f, target.slug), '']));
  updates[NAME_KEY(spec, target.slug)] = '';

  if (target.isDefault) {
    const next = listTargets(spec).find((t) => t.slug !== target.slug && t.complete);
    updates[DEFAULT_KEY(spec)] = next ? next.name : '';
  }
  writeSecrets(spec.provider, updates);
  return target;
}

/**
 * Rename a target. The name is the only label a user has for an account the
 * provider will not identify, so a bad one is worth fixing — and adopting an
 * existing configuration hands out names like "default" that mean nothing.
 */
export function renameTarget(spec, from, to) {
  const target = listTargets(spec).find((t) => t.slug === slug(from));
  if (!target) throw new Error(`There is no ${spec.label} called "${from}".`);
  if (slug(to) === target.slug) {
    // Same slug, different spelling — just restate the display name.
    writeSecrets(spec.provider, { [NAME_KEY(spec, target.slug)]: to });
    return { ...target, name: to };
  }
  if (listTargets(spec).some((t) => t.slug === slug(to))) {
    throw new Error(`There is already a ${spec.label} called "${to}".`);
  }

  const updates = { [NAME_KEY(spec, target.slug)]: '', [NAME_KEY(spec, slug(to))]: to };
  for (const [field, prefix] of Object.entries(spec.fields)) {
    updates[`${prefix}_${slug(to)}`] = target.fields[field] || '';
    updates[`${prefix}_${target.slug}`] = '';
  }
  if (target.isDefault) updates[DEFAULT_KEY(spec)] = to;

  writeSecrets(spec.provider, updates);
  return { ...target, name: to, slug: slug(to) };
}

/** Pull `--<flag> <name>` out of an argument list, returning the rest. */
export function takeTargetFlag(args, spec) {
  const rest = [...args];
  for (const flag of [`--${spec.flag}`, '--target']) {
    const at = rest.indexOf(flag);
    if (at === -1) continue;
    const value = rest[at + 1];
    if (!value) throw new Error(`${flag} needs a name after it`);
    rest.splice(at, 2);
    return { name: value, args: rest };
  }
  return { name: '', args: rest };
}
