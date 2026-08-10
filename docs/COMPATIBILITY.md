# Agent compatibility

Every skill in this repo is a conformant [Agent Skills](https://agentskills.io/specification) directory: a `SKILL.md` with `name` + `description` frontmatter, bundled files referenced by paths relative to the skill root, and no vendor-specific variables in the body.

That is what makes one directory work everywhere. The table below is the verified discovery behaviour of each supported agent.

## Verified discovery paths

Checked against each vendor's own documentation on 2026-08-11. Paths are quoted from those docs; see Sources.

| Agent | Reads `~/.agents/skills/` | Other user-level paths | Project-level paths |
| :-- | :-: | :-- | :-- |
| **Claude Code** | **No** | `~/.claude/skills/` | `.claude/skills/` (plus nested, and `--add-dir`) |
| **Codex** | Yes | `/etc/codex/skills` (admin) | `.agents/skills` in cwd, parent, and repo root |
| **OpenCode** | Yes | `~/.config/opencode/skills/`, `~/.claude/skills/` | `.agents/skills/`, `.opencode/skills/`, `.claude/skills/` |
| **Cursor** | Yes | `~/.cursor/skills/`, `~/.claude/skills/`, `~/.codex/skills/` | `.agents/skills/`, `.cursor/skills/`, `.claude/skills/`, `.codex/skills/` |
| **Gemini CLI** | Yes — takes precedence | `~/.gemini/skills/` | `.agents/skills/` (precedence), `.gemini/skills/` |
| **GitHub Copilot / VS Code** | Yes | `~/.copilot/skills/` | `.agents/skills/`, `.github/skills/`, `.claude/skills/` |
| **Amp** | Yes | `~/.config/agents/skills/`, `~/.config/amp/skills/` | `.agents/skills/`, `.claude/skills/` |
| **Goose** | Yes | `~/.config/goose/skills/`, `~/.claude/skills/` | `.agents/skills/`, `.goose/skills/`, `.claude/skills/` |

None of these require a manifest, registration, or enablement step. Dropping a valid skill directory in place is sufficient.

## What this means for distribution

**Seven of the eight read `~/.agents/skills/`.** That single directory is the primary install target, and `./scripts/install.sh` writes there by default.

**Claude Code is the one holdout.** It reads only `~/.claude/skills/`, `.claude/skills/`, and installed plugins. It gets its own native channel instead — the plugin marketplace in this repo, which is strictly better there: versioned installs, one-command updates, and the ability to bundle agents, hooks and MCP servers alongside the skill.

```
/plugin marketplace add itqanlab/skills
```

`./scripts/install.sh --claude` is the fallback for anyone who would rather copy into `~/.claude/skills/` than register a marketplace. Because each skill folder carries a `.claude-plugin/plugin.json`, Claude Code loads a folder dropped there as a plugin named `<name>@skills-dir`, so it keeps full plugin capability either way. That file is stripped when installing to the neutral path, where other agents have no use for it.

## Overlap is safe

Several agents read both `~/.agents/skills/` and `~/.claude/skills/`, so installing to both makes the same skill visible twice. This is handled by the agents themselves — Amp, for instance, "uses the first skill with a given frontmatter `name`" in its documented precedence order, and Cursor, Goose and OpenCode treat their vendor paths as backward-compatible fallbacks behind the neutral path. Names stay unique because the directory name, the frontmatter `name`, and the plugin `name` are all required to match.

Still, the default install writes to exactly one location. Use `--all` only if you actually want belt and braces.

## Project-level installs

Every agent except Claude Code reads `.agents/skills/` from the working tree, and Codex, OpenCode, Cursor and Amp walk up parent directories to find it. Committing a skill to `.agents/skills/` in a repository therefore ships it to everyone who clones that repo, with no install step.

```bash
./scripts/install.sh --project          # writes ./.agents/skills/
```

For Claude Code the repo-level equivalent is `.claude/skills/`, or declaring the plugin in the repository's `.claude/settings.json` so it installs at session start.

## Writing for all eight

The rules that keep a skill portable are in [AUTHORING.md](AUTHORING.md). The two that break portability most often:

- **Relative paths only.** `scripts/watch.sh`, never `${CLAUDE_PLUGIN_ROOT}/...` — that variable resolves in Claude Code and nowhere else.
- **No vendor names in the body.** The `SKILL.md` body is read verbatim by all eight agents. Slash-command syntax, UI references and config-file names belong in `README.md` or `.claude-plugin/`, not in the skill instructions.

## Sources

- [Agent Skills specification](https://agentskills.io/specification) · [overview and client showcase](https://agentskills.io)
- [Claude Code — skills](https://code.claude.com/docs/en/skills) · [plugin marketplaces](https://code.claude.com/docs/en/plugin-marketplaces) · [plugins reference](https://code.claude.com/docs/en/plugins-reference)
- [Codex — build skills](https://learn.chatgpt.com/docs/build-skills)
- [OpenCode — skills](https://opencode.ai/docs/skills/)
- [Cursor — skills](https://cursor.com/docs/context/skills)
- [Gemini CLI — skills](https://geminicli.com/docs/cli/skills/)
- [GitHub Copilot — about agent skills](https://docs.github.com/en/copilot/concepts/agents/about-agent-skills)
- [Amp — manual](https://ampcode.com/manual)
- [Goose — using skills](https://goose-docs.ai/docs/guides/context-engineering/using-skills/)
