# MCP servers

Each subdirectory here is an independently published npm package, wired as a workspace of the repo root `package.json`.

```
mcp/
└── <server-name>/
    ├── package.json     own name + own version — this is what npm publishes
    ├── src/
    └── README.md
```

Publish one:

```bash
npm publish -w mcp/<server-name> --access public
```

A server should usually also appear as a plugin in `.claude-plugin/marketplace.json` with an `mcpServers` field, so users install it with `/plugin install` instead of hand-editing MCP config.

Same agnostic bar as skills: no hardcoded accounts, no bundled tokens, credentials read from environment variables that the README documents. See [../docs/AUTHORING.md](../docs/AUTHORING.md).

Empty for now — nothing has been migrated here yet.
