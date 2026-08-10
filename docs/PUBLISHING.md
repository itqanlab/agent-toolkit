# Publishing

One repo serves every channel and every component type. Nothing here needs a repo per tool.

| Component | Channel | Reaches |
| :-- | :-- | :-- |
| Skills (`skills/`) | Neutral path, plus the marketplace | All 8 agents |
| Plugins (`plugins/`) | Marketplace | Claude Code |
| MCP servers (`mcp/`) | npm, plus optional marketplace entry | Any MCP client |

The reason a single directory can serve two audiences is that `skills/<name>/` is simultaneously a conformant [Agent Skills](https://agentskills.io) directory and a Claude Code plugin directory. Vendor packaging sits in `.claude-plugin/`, which every other agent ignores.

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

The repo root **is** the marketplace. `.claude-plugin/marketplace.json` is the catalog; each entry's `source` points at `./skills/<name>`.

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

## 3. Skill indexes and community catalogs

Directories like skills.sh and the `awesome-claude-*` lists are catalogs of links, not package registries. They point at a repo and a path, so a monorepo is the common case.

For each submission supply: repo URL, the `skills/<name>` subdirectory path, a one-line description, and the install commands above. Keep the per-skill `README.md` good — that is what a reviewer reads.

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
2. `claude plugin validate .` and `claude plugin validate skills/<name>` pass
3. Version bumped in `plugin.json`, the marketplace entry, and the skill's `metadata.version`
4. Skill `README.md` reflects any new flags
5. `./scripts/install.sh <name> --link --force`, then run the skill once, end to end
6. No vendor variables or absolute paths: `grep -rn 'CLAUDE_PLUGIN_ROOT\|/Users/\|~/\.claude' skills/*/SKILL.md skills/*/scripts/` returns nothing
7. No secrets: confirm `.env`, tokens and account IDs are absent
8. Push, `claude plugin tag skills/<name>`, then install from scratch in a clean session to confirm
