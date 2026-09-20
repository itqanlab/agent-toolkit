# Plugins

Every item in this catalog lives here, as `plugins/<name>/`. A plugin holds its skill in a `skills/` folder.

```
plugins/<name>/
├── .claude-plugin/plugin.json      # Claude Code manifest, written by hand
├── .codex-plugin/plugin.json       # Codex manifest, generated. Do not edit
├── skills/<name>/                  # the skill: SKILL.md, README.md, CHANGELOG.md, scripts/
├── agents/<agent-name>.md          # later: subagent definitions (Claude Code)
├── hooks/hooks.json                # later: lifecycle hooks (Claude Code)
├── .mcp.json                       # later: MCP servers this plugin provides
└── .app.json                       # later: connectors (Codex)
```

## Why the skill is nested

Codex requires it. A Codex plugin must keep its skills in `skills/<name>/`, and Codex's own validator rejects any other place. Claude Code and the open standard accept the same shape. So this one layout serves every agent from a single source, with no copies, no extra branch and no install flags.

The skill folder is still a plain open-standard skill. `scripts/install.sh` copies just that folder for every other agent, and it carries its own README and CHANGELOG.

## What goes here

| You have | Put it in |
| :-- | :-- |
| One skill, scripts only | `plugins/<name>/skills/<name>/` |
| A skill plus a subagent, hook or command | The same plugin folder, next to `skills/` |
| An MCP server or a connector | The same plugin folder, as `.mcp.json` or `.app.json` |
| A standalone MCP server published to npm | [`mcp/<name>/`](../mcp) |

The generator supports one skill per plugin, named like the plugin. Bundles come later. Add the folders above when the first one is needed, and teach `scripts/build-catalog.mjs` about it.

## What is generated

`npm run catalog` writes `.codex-plugin/plugin.json` in every plugin, `.claude-plugin/marketplace.json` and `.agents/plugins/marketplace.json` at the root, and the table in the root README. It also copies every skill folder into `.agents/skills/<name>/`, because Amp cannot find a skill under `plugins/`. Edit the skill under `plugins/`, never the copy. `scripts/validate.sh` fails if any of these is out of date. See [docs/AUTHORING.md](../docs/AUTHORING.md).

## Portability

Skills are portable across all eight agents. See [docs/COMPATIBILITY.md](../docs/COMPATIBILITY.md). Subagents, hooks and commands are Claude Code specific. Express a capability as a skill whenever instructions plus a script can do the job.
