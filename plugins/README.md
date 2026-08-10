# Plugins

Multi-component bundles for Claude Code: a plugin that ships **more than one skill**, or that combines skills with subagents, hooks, commands, or MCP server wiring.

```
plugins/<name>/
├── .claude-plugin/plugin.json
├── skills/<skill-name>/SKILL.md    # one or more
├── agents/<agent-name>.md          # subagent definitions
├── commands/<command>.md           # flat command files
├── hooks/hooks.json                # lifecycle hooks
└── .mcp.json                       # MCP servers this plugin provides
```

Register each bundle in `.claude-plugin/marketplace.json` with `"source": "./plugins/<name>"`.

## When to put something here instead of `skills/`

A single skill with no other components belongs in [`skills/`](../skills), where the skill directory doubles as its own plugin root. That layout keeps the directory portable — it is a valid Agent Skills directory that any of the eight supported agents can read directly.

Use `plugins/` only when the bundle genuinely needs more:

| You have | Put it in |
| :-- | :-- |
| One skill, scripts only | `skills/<name>/` |
| Several related skills | `plugins/<name>/skills/` |
| A skill plus a subagent, hook, or command | `plugins/<name>/` |
| An MCP server users install via `/plugin` | `plugins/<name>/` with `.mcp.json` |
| A standalone MCP server published to npm | [`mcp/<name>/`](../mcp) |

## Portability

Skills are portable across all eight agents in [docs/COMPATIBILITY.md](../docs/COMPATIBILITY.md). Subagents, hooks and commands are **Claude Code specific** — no equivalent exists in the Agent Skills standard, and other agents ignore them.

That asymmetry decides the split. Anything portable should be expressed as a skill so every agent benefits. Reach for a Claude-only component when the capability genuinely cannot be expressed as instructions plus a script — a hook that must fire on a tool event, or a subagent that needs its own context window.

A plugin's skills stay portable even inside a bundle: `plugins/<name>/skills/<skill>/` can still be copied to `~/.agents/skills/` by hand. `scripts/install.sh` only walks `skills/` at the repo root, so bundled skills are not installed for other agents automatically.

Empty for now — nothing has been migrated here yet.
