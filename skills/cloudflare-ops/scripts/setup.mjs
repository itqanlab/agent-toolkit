#!/usr/bin/env node
// setup.mjs — connect a Cloudflare account in two steps.
//
// Cloudflare has 390-odd separate permissions and no "select all" control, so
// building a working token by hand is a long, error-prone click-through. It does
// however let a token that can manage tokens create other tokens, so the user
// ticks two boxes and this script builds the real one.
//
// Step 1 (begin)  — the user creates a small, temporary token and pastes it in.
// Step 2 (finish) — this creates the real token, saves it, and deletes the
//                   temporary one so the pasted value stops being useful.

import { hasSecret, providerPath, readSecrets, recordState, scaffold, writeSecrets } from '../lib/store.mjs';
import { request, CloudflareError } from './cf.mjs';

const PROVIDER = 'cloudflare';
const TOKEN_KEY = 'CLOUDFLARE_API_TOKEN';
const BOOTSTRAP_KEY = 'CLOUDFLARE_SETUP_TOKEN';
const TOKEN_NAME = 'Agent toolkit (full access)';

const DASHBOARD = 'https://dash.cloudflare.com/profile/api-tokens';

// --- step 1 ------------------------------------------------------------------

function begin({ force }) {
  if (!force && hasSecret(PROVIDER, TOKEN_KEY)) {
    console.log('Cloudflare is already connected. Nothing to do.');
    console.log('To replace the saved token, run this again with --force.');
    return;
  }

  scaffold(PROVIDER, [
    { name: BOOTSTRAP_KEY, note: 'Temporary. Paste the token from the steps below. It is deleted automatically once setup finishes.' },
    { name: TOKEN_KEY, note: 'Filled in for you. Leave this empty.' },
  ]);

  console.log(`
Connecting your Cloudflare account. This takes about two minutes.

STEP 1 — create a temporary token

  1. Open this page and sign in:

       ${DASHBOARD}

  2. Click the "Create Token" button.

  3. Scroll to the bottom of the list to "Create Custom Token"
     and click "Get started".

  4. In "Token name", type:  Agent setup (temporary)

  5. Under "Permissions" you will see three dropdowns side by side.
     Set the first row to:

       User   |   API Tokens   |   Edit

     Click "+ Add more" and set the second row to:

       User   |   User Details   |   Read

     Click "+ Add more" once more and set the third row to:

       Account   |   Account Settings   |   Read

     Three rows in total. Leave everything else alone.

  6. Just below, under "Account Resources", set the two dropdowns to:

       Include   |   All accounts

  7. Click "Continue to summary", then "Create Token".

  8. Cloudflare now shows the token once, and never again.
     Click the copy button next to it.

STEP 2 — paste it in

  Open this file in any text editor:

     ${providerPath(PROVIDER)}

  Find the line that starts with ${BOOTSTRAP_KEY}= and paste the token
  straight after the "=", with no quotes and no spaces. Save the file.

STEP 3 — tell me you are done

  Then run:

     node scripts/setup.mjs finish

  I will build the real token, save it, and delete the temporary one for you.
`);
}

// --- step 2 ------------------------------------------------------------------

/** A freshly created token needs a few seconds before it authenticates. */
async function waitForToken(token, attempts = 6) {
  for (let attempt = 1; ; attempt += 1) {
    try {
      return await request('/user/tokens/verify', { token });
    } catch (err) {
      if (attempt >= attempts) throw err;
      await new Promise((resolve) => setTimeout(resolve, 3000));
    }
  }
}

/**
 * Every permission Cloudflare offers, grouped by the kind of thing it applies
 * to. Two deliberate omissions:
 *
 * - Bucket-scoped permissions need a named bucket, and the account-wide R2
 *   permissions already cover working with buckets.
 * - Token-management permissions are refused outright by Cloudflare when the
 *   request itself comes from a token ("sub-token is not allowed to have
 *   permissions to manage other tokens"). So the token this builds can do
 *   everything except mint more tokens — which is a reasonable place for the
 *   chain to stop. Rotating means creating a fresh temporary token.
 */
function buildPolicies(groups, accounts, user) {
  const usable = groups.filter((g) => !/API Tokens/i.test(g.name || ''));
  const byScope = (scope) => usable.filter((g) => g.scopes?.length === 1 && g.scopes[0] === scope).map((g) => ({ id: g.id }));

  const accountGroups = byScope('com.cloudflare.api.account');
  const zoneGroups = byScope('com.cloudflare.api.account.zone');
  const userGroups = byScope('com.cloudflare.api.user');

  const policies = [];
  for (const account of accounts) {
    const resources = { [`com.cloudflare.api.account.${account.id}`]: '*' };
    if (accountGroups.length) policies.push({ effect: 'allow', resources, permission_groups: accountGroups });
    // Zone-scoped permissions attached to the account resource mean "every zone
    // in this account", including zones added later.
    if (zoneGroups.length) policies.push({ effect: 'allow', resources, permission_groups: zoneGroups });
  }
  if (user && userGroups.length) {
    policies.push({
      effect: 'allow',
      resources: { [`com.cloudflare.api.user.${user.id}`]: '*' },
      permission_groups: userGroups,
    });
  }
  return policies;
}

async function finish() {
  const bootstrap = readSecrets(PROVIDER)[BOOTSTRAP_KEY];
  if (!bootstrap) {
    console.error(
      `Nothing pasted yet.\n\n` +
      `Open this file, paste the temporary token after ${BOOTSTRAP_KEY}= and save it:\n` +
      `  ${providerPath(PROVIDER)}\n\n` +
      `If you have not created the token yet, run:  node scripts/setup.mjs begin`,
    );
    process.exit(1);
  }

  console.log('Checking the temporary token...');
  let identity;
  try {
    identity = await waitForToken(bootstrap);
  } catch {
    console.error(
      'Cloudflare did not accept that token.\n\n' +
      'The most common causes are an extra space, a partial copy, or the token\n' +
      'having been deleted. Create a fresh one and paste it again:\n' +
      `  node scripts/setup.mjs begin --force`,
    );
    process.exit(1);
  }
  const bootstrapId = identity.result?.id;

  console.log('Reading your account...');
  const accounts = await request('/accounts', { token: bootstrap }).then((p) => p.result);
  const user = await request('/user', { token: bootstrap }).then((p) => p.result).catch(() => null);
  // Cloudflare answers this call with an empty list rather than an error when
  // the token lacks account access, so an empty result is a permissions problem,
  // not an account with nothing in it.
  if (!accounts.length) {
    console.error(
      'The temporary token works, but it cannot see any Cloudflare account.\n\n' +
      'One permission row is missing. Go back to the token you just made,\n' +
      `open it from ${DASHBOARD}, click "Edit", and add:\n\n` +
      '    Account   |   Account Settings   |   Read\n\n' +
      'and under "Account Resources" choose:\n\n' +
      '    Include   |   All accounts\n\n' +
      'Save it, then run:  node scripts/setup.mjs finish',
    );
    process.exit(1);
  }
  console.log(`  ${accounts.map((a) => a.name).join(', ')}`);

  console.log('Building the permanent token...');
  const groups = await request('/user/tokens/permission_groups', {
    token: bootstrap,
    query: { per_page: 1000 },
  }).then((p) => p.result);

  const policies = buildPolicies(groups, accounts, user);
  const created = await request('/user/tokens', {
    method: 'POST',
    token: bootstrap,
    body: { name: `${TOKEN_NAME} — ${new Date().toISOString().slice(0, 10)}`, policies },
  }).then((p) => p.result);

  writeSecrets(PROVIDER, { [TOKEN_KEY]: created.value, [BOOTSTRAP_KEY]: '' });
  console.log('Saved. Checking it works...');
  await waitForToken(created.value);

  // The temporary token can create tokens, so leaving it alive would leave a
  // second key to the account lying around in the user's clipboard history.
  //
  // It has to delete itself: the token we just built has no token-management
  // permission, by design, so it cannot do this on the temporary token's behalf.
  let revoked = false;
  if (bootstrapId) {
    try {
      await request(`/user/tokens/${bootstrapId}`, { method: 'DELETE', token: bootstrap });
      revoked = true;
    } catch { /* reported below; not fatal */ }
  }

  recordState(PROVIDER, {
    token_id: created.id,
    token_name: created.name,
    verified_at: new Date().toISOString(),
    accounts: accounts.map((a) => ({ id: a.id, name: a.name })),
  });

  console.log(`
Done. Cloudflare is connected.

  account:    ${accounts.map((a) => a.name).join(', ')}
  signed in:  ${user?.email || '(not available)'}
  permissions: ${policies.reduce((n, p) => n + p.permission_groups.length, 0)} granted
  temporary token: ${revoked ? 'deleted' : 'COULD NOT BE DELETED — remove "Agent setup (temporary)" yourself at ' + DASHBOARD}

You will not need to open the Cloudflare dashboard again.
To undo this later, delete "${created.name}" from ${DASHBOARD}.
`);
}

// --- status ------------------------------------------------------------------

async function status() {
  if (!hasSecret(PROVIDER, TOKEN_KEY)) {
    console.log('Cloudflare is not connected yet. Run:  node scripts/setup.mjs begin');
    process.exitCode = 1;
    return;
  }
  const [{ result: user }, { result: accounts }] = await Promise.all([
    request('/user').catch(() => ({ result: null })),
    request('/accounts'),
  ]);
  console.log('Cloudflare is connected.');
  console.log(`  signed in: ${user?.email || '(token has no user access)'}`);
  for (const a of accounts) console.log(`  account:   ${a.name}`);
}

// --- command line ------------------------------------------------------------

const [command = 'status', ...rest] = process.argv.slice(2);
const force = rest.includes('--force');

try {
  if (command === 'begin') begin({ force });
  else if (command === 'finish') await finish();
  else if (command === 'status') await status();
  else {
    console.error('usage: setup.mjs <begin [--force]|finish|status>');
    process.exit(2);
  }
} catch (err) {
  console.error(err instanceof CloudflareError ? err.message : `error: ${err.message}`);
  process.exit(1);
}
