# zernio-ops

Use every Zernio workspace you have from one MCP server.

## Just ask

Once the plugin is installed, say what you want in your own words:

> *"connect my Zernio"*
> *"add a second Zernio workspace"*
> *"which accounts are connected?"*
> *"schedule this video on my TikTok for tomorrow at 6pm"*

The agent sets up the keys and checks them. The one thing you do by hand is paste each API key into a file. That way the key never goes through a chat window.

## Why one server

Zernio ties each API key to one workspace. An MCP entry sends one key, so it sees one workspace. With three workspaces you would need three MCP entries and three copies of every tool.

This plugin runs one server, `zernio`, that holds every key, however many there are. Each tool takes an optional `workspace` name, and a call with an `account_id` goes to the workspace that owns that account by itself.

## Keys

One file, one line per workspace. The name after `ZERNIO_KEY_` is yours to pick:

```
ZERNIO_KEY_A=...
ZERNIO_KEY_BRAND=...
```

The file is `~/.itqan-agent-toolkit/credentials/zernio.env`, or under `AGENT_TOOLKIT_HOME` when that is set. It is the same credential store every toolkit skill uses.

```bash
node scripts/setup.mjs add brand   # adds an empty ZERNIO_KEY_BRAND= line for you to fill in
node scripts/setup.mjs status      # each workspace: does the key work, which accounts it sees
```

Restart the agent after adding a key. The server reads the file when it starts.

## Without the plugin

Any MCP client can run the server directly:

```bash
claude mcp add zernio -s user -- node /path/to/zernio-ops/skills/zernio-ops/scripts/zernio-hub.mjs
```

## Requirements

Node 18 or newer. `sh scripts/setup-deps.sh` checks for it and offers to install it.
