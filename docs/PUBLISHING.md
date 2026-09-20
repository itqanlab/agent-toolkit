# Publishing

One repo serves every channel and every component type. Nothing here needs a repo per tool.

| Component | Channel | Reaches |
| :-- | :-- | :-- |
| Skills (`plugins/*/skills/`) | Neutral path | All 8 agents |
| Plugins (`plugins/`) | Claude Code marketplace, and Codex marketplace | Claude Code, Codex |
| MCP servers (`mcp/`) | npm, plus optional marketplace entry | Any MCP client |

The reason one folder can serve every channel is that each item is a plugin folder holding a plain [Agent Skills](https://agentskills.io) folder in `skills/<name>/`. Claude Code and Codex read the plugin. Every other agent reads just the skill folder. Vendor manifests sit in `.claude-plugin/` and `.codex-plugin/`, which the other agents never look at. The Codex manifest and both catalogs are generated from the source by `npm run catalog`. So is one copy of each skill folder in `.agents/skills/<name>/`, which exists only because Amp does not look inside `plugins/`. Edit the skill under `plugins/`. The copy is checked byte for byte, so a hand edit fails `validate.sh`.

## 1. Any conformant agent — the vendor-neutral path

Cursor, Gemini CLI and other conformant agents read `~/.agents/skills/` (user level) and `.agents/skills/` (project level), and give that neutral path precedence over their own vendor directories. Several also read `~/.claude/skills/` and `~/.codex/skills/` for backward compatibility.

So distribution is just the repo:

```bash
git clone https://github.com/itqanlab/agent-toolkit && cd agent-toolkit
./scripts/install.sh      # or .\scripts\install.ps1 on Windows
```

The installer **copies** by default. Copies behave identically on every OS and under every agent. `--link` (symlink) and `-Link` (Windows directory junction, no admin required) exist for development only.

Never commit a symlink inside a skill directory. Git stores symlinks as a special blob, and Git for Windows checks them out as plain text files unless `core.symlinks` is enabled — so a committed symlink silently becomes a broken text file for a large share of users.

## 2. Claude Code marketplace — native, zero infrastructure

The repo root **is** the marketplace. `.claude-plugin/marketplace.json` is the catalog; each entry's `source` points at `./plugins/<name>`. The file is generated from the plugin folders by `npm run catalog`, so do not edit its `plugins` list by hand.

```bash
claude plugin validate .
git push
```

Users then run:

```
/plugin marketplace add itqanlab/agent-toolkit
/plugin install watch-video@itqan
```

Notes that matter:

- A user can register only **one** marketplace per name. `itqan` must therefore hold every plugin — which is exactly why this is a monorepo.
- `/plugin install` **copies** into `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/`. It is not a live reference to your working tree, so repo edits do not appear until you bump the version and run `/plugin marketplace update`.
- Relative `source` paths resolve against a local clone of the marketplace, so they work for git and local-directory sources. They break if someone adds the marketplace by direct URL to the raw `marketplace.json`, because only that one file is fetched. Distribute the repo, not the file.
- Marketplace names that impersonate Anthropic are blocked, and a set of official names is reserved — `agent-skills` among them. `itqan` is safe.
- `claude plugin tag` creates a `{name}--v{version}` git tag and checks that `plugin.json` and the marketplace entry agree on the version. Use it for releases.

### Codex marketplace

`.agents/plugins/marketplace.json` is the catalog Codex reads, and it reads it before the Claude one. It is generated too. Users run:

```
codex plugin marketplace add itqanlab/agent-toolkit
codex plugin add watch-video@itqan
```

A plain `add` from GitHub works. It needs no `--ref` and no `--sparse`, because every plugin sits at a fixed path on `main`. To update, run `codex plugin marketplace upgrade itqan` and then `codex plugin add <name>@itqan` again. Codex replaces the installed version and starts using it in a new session.

## 3. Skill indexes and community catalogs

Directories like skills.sh and the `awesome-claude-*` lists are catalogs of links, not package registries. They point at a repo and a path, so a monorepo is the common case.

For each submission supply: repo URL, the `plugins/<name>/skills/<name>` subdirectory path, a one-line description, and the install commands above. Keep the per-skill `README.md` good — that is what a reviewer reads.

Submission requirements change; check each index's current CONTRIBUTING before submitting.

## 4. MCP servers — npm workspaces

MCP servers are ordinary packages. The root `package.json` declares `workspaces: ["mcp/*"]`, so each server under `mcp/<name>/` has its own name and version and publishes independently:

```bash
npm publish -w mcp/<name> --access public
```

A server can also be listed as a plugin in `marketplace.json` via the plugin `mcpServers` field, so Claude Code users get it through `/plugin install` instead of hand-editing MCP config.

Skills and MCP servers solve different problems and are not alternatives. A skill is procedural knowledge plus bundled scripts, loaded progressively. An MCP server is a live tool surface. Reach for MCP when the capability needs a persistent connection, credentials, or a typed tool contract; reach for a skill when a markdown file and a shell script would do.

## Release checklist

1. `./scripts/validate.sh` passes (it runs the upstream `skills-ref` reference validator when `uv` is installed)
2. `claude plugin validate .` and `claude plugin validate plugins/<name>` pass. On a machine with Codex, `validate.sh` also runs Codex's own plugin validator
3. Version bumped in `plugin.json` and the skill's `metadata.version`, a `CHANGELOG.md` entry added for it, then `npm run catalog` run and its output committed
4. Skill `README.md` reflects any new flags
5. `./scripts/install.sh <name> --link --force`, then run the skill once, end to end
6. No vendor variables or absolute paths: `grep -rn 'CLAUDE_PLUGIN_ROOT\|/Users/\|~/\.claude' plugins/*/skills/*/SKILL.md plugins/*/skills/*/scripts/` returns nothing
7. No secrets: confirm `.env`, tokens and account IDs are absent. The `Compatibility` workflow is green on all three operating systems
8. Push, `claude plugin tag plugins/<name>`, then install from scratch in a clean session to confirm. For Codex, run `codex plugin marketplace add itqanlab/agent-toolkit` and `codex plugin add <name>@itqan` in a throwaway `CODEX_HOME`, then `codex debug prompt-input hello` to see that the skill reaches the model
