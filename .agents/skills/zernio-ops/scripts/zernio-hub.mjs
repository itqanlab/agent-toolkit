#!/usr/bin/env node
// zernio-hub: one MCP server in front of several Zernio workspaces.
//
// Zernio scopes an API key to one workspace, and an MCP entry sends one static key, so one
// entry can only ever see one workspace. This server holds every key and fronts them all.
// The workspaces are whatever ZERNIO_KEY_<NAME> lines the toolkit credential store holds
// (lib/workspaces.mjs). No count is fixed: one line is one workspace, and a new one needs only a
// restart. Keys never come from argv or the MCP config, so they never show up in a process list
// or a config file.
//
// Every tool gets an optional `workspace` argument. Without it, the workspace is found from
// `account_id`; `accounts_list` with no workspace lists all of them.
import { createInterface } from 'node:readline';
import { keysFile, readyWorkspaces } from '../lib/workspaces.mjs';

const UPSTREAM = 'https://mcp.zernio.com/mcp';
const VERSION = '1.0.0';

const keys = readyWorkspaces();
const WS = Object.keys(keys).sort();
if (!WS.length) {
  process.stderr.write(`zernio-hub: no ZERNIO_KEY_<NAME> lines with a key in ${keysFile()}. Run the zernio-ops skill to set one up.\n`);
}

const sessions = {};
let nextId = 1;

async function rpc(ws, method, params, retry = true) {
  const headers = {
    Authorization: `Bearer ${keys[ws]}`,
    'Content-Type': 'application/json',
    Accept: 'application/json, text/event-stream',
  };
  if (sessions[ws]) headers['Mcp-Session-Id'] = sessions[ws];
  const res = await fetch(UPSTREAM, {
    method: 'POST',
    headers,
    body: JSON.stringify({ jsonrpc: '2.0', id: nextId++, method, params }),
  });
  const sid = res.headers.get('mcp-session-id');
  if (sid) sessions[ws] = sid;
  if (!res.ok && retry && method !== 'initialize') {
    delete sessions[ws];
    await init(ws);
    return rpc(ws, method, params, false);
  }
  if (!res.ok) throw new Error(`Zernio ${ws}: HTTP ${res.status}`);
  const text = await res.text();
  const data = text.split('\n').find((l) => l.startsWith('data:'));
  const msg = JSON.parse(data ? data.slice(5) : text);
  if (msg.error) throw new Error(`Zernio ${ws}: ${msg.error.message}`);
  return msg.result;
}

async function init(ws) {
  await rpc(ws, 'initialize', {
    protocolVersion: '2025-03-26',
    capabilities: {},
    clientInfo: { name: 'zernio-hub', version: VERSION },
  });
}

const call = async (ws, name, args) => {
  if (!sessions[ws]) await init(ws);
  return rpc(ws, 'tools/call', { name, arguments: args });
};

// account id -> workspace. Filled lazily from accounts_list on every workspace.
const owner = {};
const labels = {};
async function scanAccounts() {
  await Promise.all(
    WS.filter((w) => keys[w]).map(async (w) => {
      try {
        const r = await call(w, 'accounts_list', {});
        labels[w] = r.content?.[0]?.text ?? '';
        for (const m of labels[w].matchAll(/\(ID: ([A-Za-z0-9]+)\)/g)) owner[m[1]] = w;
      } catch (e) {
        labels[w] = `error: ${e.message}`;
      }
    }),
  );
}

async function pickWorkspace(args) {
  if (args.workspace) return String(args.workspace).toLowerCase();
  // call_tool wraps the real arguments one level down
  const inner = args.arguments && typeof args.arguments === 'object' ? args.arguments : {};
  if (inner.workspace) return String(inner.workspace).toLowerCase();
  const ids = [args.account_id, inner.account_id, ...(args.account_ids ?? []), ...(inner.account_ids ?? [])].filter(Boolean);
  if (ids.length) {
    if (!owner[ids[0]]) await scanAccounts();
    if (owner[ids[0]]) return owner[ids[0]];
  }
  return null;
}

let toolsCache;
async function listTools() {
  if (toolsCache) return toolsCache;
  const first = WS.find((w) => keys[w]);
  if (!first) return [];
  if (!sessions[first]) await init(first);
  const { tools } = await rpc(first, 'tools/list', {});
  const ws = {
    type: 'string',
    enum: WS,
    description:
      'Zernio workspace (each holds its own accounts). Optional: found from account_id when omitted. Call accounts_list with no workspace to see all of them.',
  };
  toolsCache = tools.map((t) => ({
    ...t,
    inputSchema: {
      ...t.inputSchema,
      properties: { ...(t.inputSchema?.properties ?? {}), workspace: ws },
    },
  }));
  return toolsCache;
}

async function handleCall({ name, arguments: raw = {} }) {
  const { workspace: _drop, ...args } = raw;
  if (name === 'accounts_list' && !raw.workspace && !args.profile_id) {
    await scanAccounts();
    const text = WS.filter((w) => labels[w])
      .map((w) => `== workspace ${w} ==\n${labels[w]}`)
      .join('\n\n');
    return { content: [{ type: 'text', text }] };
  }
  const ws = await pickWorkspace(raw);
  if (!ws || !keys[ws]) {
    return {
      isError: true,
      content: [
        {
          type: 'text',
          text: `Cannot tell which Zernio workspace to use. Pass workspace (one of: ${WS.join(', ')}), or an account_id from accounts_list.`,
        },
      ],
    };
  }
  return call(ws, name, args);
}

function reply(id, result, error) {
  process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id, ...(error ? { error } : { result }) }) + '\n');
}

const rl = createInterface({ input: process.stdin });
rl.on('line', async (line) => {
  if (!line.trim()) return;
  let msg;
  try {
    msg = JSON.parse(line);
  } catch {
    return;
  }
  if (msg.id === undefined) return; // notifications need no reply
  try {
    if (msg.method === 'initialize') {
      reply(msg.id, {
        protocolVersion: msg.params?.protocolVersion ?? '2025-03-26',
        capabilities: { tools: {} },
        serverInfo: { name: 'zernio', version: VERSION },
      });
    } else if (msg.method === 'ping') reply(msg.id, {});
    else if (msg.method === 'tools/list') reply(msg.id, { tools: await listTools() });
    else if (msg.method === 'tools/call') reply(msg.id, await handleCall(msg.params));
    else reply(msg.id, null, { code: -32601, message: `Method not found: ${msg.method}` });
  } catch (e) {
    reply(msg.id, { isError: true, content: [{ type: 'text', text: String(e.message) }] });
  }
});
