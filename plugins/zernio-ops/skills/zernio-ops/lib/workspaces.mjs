// workspaces.mjs: which Zernio workspaces exist, read from the toolkit credential store.
//
// A workspace is any ZERNIO_KEY_<NAME> line in <store root>/credentials/zernio.env. There is no
// fixed list and no fixed count: one line is one workspace. <NAME> is letters, digits and
// underscores, so `ZERNIO_KEY_A` and `ZERNIO_KEY_CLIENT_2` both work. The workspace id the tools
// use is the name in lowercase.
import { readSecrets, providerPath } from './store.mjs';

export const PROVIDER = 'zernio';
const PREFIX = 'ZERNIO_KEY_';
const NAME = /^[A-Z0-9][A-Z0-9_]*$/;
const PLACEHOLDER = /^(<|paste|your[-_])/i;

export const keysFile = () => providerPath(PROVIDER);
export const keyName = (ws) => PREFIX + String(ws).toUpperCase();
export const validName = (ws) => NAME.test(String(ws).toUpperCase());

/** Every workspace line, filled or not: { id: value }. Import this; never print the values. */
export function allWorkspaces() {
  const out = {};
  for (const [k, v] of Object.entries(readSecrets(PROVIDER))) {
    if (!k.startsWith(PREFIX)) continue;
    const name = k.slice(PREFIX.length);
    if (NAME.test(name)) out[name.toLowerCase()] = v;
  }
  return out;
}

/** Only the workspaces whose key is filled in. */
export function readyWorkspaces() {
  return Object.fromEntries(Object.entries(allWorkspaces()).filter(([, v]) => v && !PLACEHOLDER.test(v)));
}
