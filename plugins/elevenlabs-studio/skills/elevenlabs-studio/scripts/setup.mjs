#!/usr/bin/env node
// setup.mjs — connect an ElevenLabs account.
//
// ElevenLabs keys are simple: one form, a list of permission rows, and the key is
// shown once. There is nothing to mint. The job here is to put the key somewhere
// safe without it passing through the conversation, and to check it can do the
// five things this skill needs, including reading the credit balance.
//
//   begin [--force]  create the file and print the steps
//   finish           check the pasted key and record that it works
//   status           what is connected, and the credits left

import { hasSecret, providerPath, readSecrets, recordState, scaffold, writeSecrets, permissionWarnings } from '../lib/store.mjs';
import { call, credits, ElevenError } from './eleven.mjs';

const PROVIDER = 'elevenlabs';
const KEY = 'ELEVENLABS_API_KEY';
const DASHBOARD = 'https://elevenlabs.io/app/settings/api-keys';

// --- begin -------------------------------------------------------------------

function begin({ force }) {
  if (!force && hasSecret(PROVIDER, KEY)) {
    console.log('ElevenLabs is already connected. Nothing to do.');
    console.log('To replace the saved key, run this again with --force.');
    return;
  }

  scaffold(PROVIDER, [{ name: KEY, note: 'Your ElevenLabs API key. It starts with sk_.' }]);
  if (force) writeSecrets(PROVIDER, { [KEY]: '' });

  console.log(`
Connecting your ElevenLabs account. This takes about two minutes.

STEP 1 — create an API key

  1. Open this page and sign in:

       ${DASHBOARD}

  2. Click "Create API Key" and give it a name you will recognise later,
     such as:  agent toolkit

  3. Keep "Restrict Key" switched on, and set exactly these rows:

       Text to Speech    Access
       Sound Effects     Access
       Music             Access
       Voices            Read
       User              Read

     If there is a History row, set it to Read as well. It lets the tool
     measure the exact cost of each voice-over. Leave every other row at
     "No Access".

     User: Read matters. It is what lets the tool read your credit balance,
     and the tool refuses to spend credits it cannot count.

  4. Optional but sensible: set a credit quota on the key, so it can never
     spend more than you meant it to in a month.

  5. Click "Create". ElevenLabs shows the key once and never again.
     It starts with sk_ and is about 50 characters long. Copy it.

STEP 2 — paste it in

  Open this file in any text editor:

     ${providerPath(PROVIDER)}

  Find the line that starts with ${KEY}= and paste the key straight
  after the "=", with no quotes and no spaces. Save the file.

STEP 3 — tell me you are done

     node scripts/setup.mjs finish
`);
}

// --- finish ------------------------------------------------------------------

async function finish() {
  if (!hasSecret(PROVIDER, KEY)) {
    console.error(
      `Nothing pasted yet.\n\n` +
      `Open this file, paste the key after ${KEY}= and save it:\n` +
      `  ${providerPath(PROVIDER)}\n\n` +
      'If you have not created the key yet, run:  node scripts/setup.mjs begin',
    );
    process.exit(1);
  }
  const key = readSecrets(PROVIDER)[KEY];

  console.log('Checking the key...');
  // Both calls are free. The first proves the balance can be read, the second that
  // voices can be listed. The paid permissions cannot be tested without spending.
  const balance = await credits({ key });
  const voices = await call('GET', '/v2/voices?page_size=1', undefined, { key });

  recordState(PROVIDER, { verified_at: new Date().toISOString(), tier: balance.tier });

  const reset = balance.reset ? new Date(balance.reset * 1000).toISOString().slice(0, 10) : 'unknown';
  console.log(`
Done. ElevenLabs is connected.

  plan:          ${balance.tier}
  credits left:  ${balance.left} of ${balance.limit}, resets ${reset}
  voices:        ${voices.total_count ?? voices.voices?.length ?? 0} available to this account

Text to Speech, Sound Effects and Music cannot be checked without spending
credits. If one of them was not switched on, the first call of that kind says
which row to add, and nothing is charged.

To undo this later, delete the key at ${DASHBOARD}.
`);
}

// --- status ------------------------------------------------------------------

async function status() {
  if (!hasSecret(PROVIDER, KEY)) {
    console.log('ElevenLabs is not connected yet. Run:  node scripts/setup.mjs begin');
    console.log(`The key will live in:  ${providerPath(PROVIDER)}`);
    process.exitCode = 1;
    return;
  }
  const c = await credits();
  console.log('ElevenLabs is connected.');
  console.log(`  plan:         ${c.tier}`);
  console.log(`  credits left: ${c.left} of ${c.limit}`);
  for (const warning of permissionWarnings()) console.log(`\n! ${warning}`);
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
  console.error(err instanceof ElevenError ? err.message : `error: ${err.message}`);
  process.exit(1);
}
