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

## Tested on the real tools

The table above comes from each vendor's documentation. This one comes from running the tools against this repository. Each test used a scratch home folder, and each had a control with an empty home that found nothing, so a pass means something.

| Agent (version) | Neutral path, `~/.agents/skills` | Its own channel |
| :-- | :-- | :-- |
| Claude Code | Not applicable. It does not read that path | `claude plugin marketplace add itqanlab/agent-toolkit`, then install: works |
| Codex 0.150.0 | 7 of 7 reach the model | `codex plugin marketplace add itqanlab/agent-toolkit`, then `codex plugin add`: works |
| Gemini CLI 0.60.0 | 7 of 7 in `gemini skills list` | `gemini skills install <repo> --path plugins/<name>/skills/<name>`: installed `watch-video` from GitHub |
| OpenCode 1.18.31 | 7 of 7 in `opencode debug skill` | None used |
| GitHub Copilot CLI 1.0.86 | 7 of 7 in `copilot skill list` | `copilot plugin marketplace add itqanlab/agent-toolkit`: lists all 7, installed one |
| Amp | Not tested. It asks for a login even to list skills | Not tested |
| Cursor, Goose | Not tested. One is an editor, the other a binary | Not tested |

One odd result: the first OpenCode run listed 6 of 7 and missed `toolkit-credentials`. Six later runs, four of them on fresh homes, all listed 7. I could not reproduce the miss and cannot explain it.

## What this means for distribution

**Seven of the eight read `~/.agents/skills/`.** That single directory is the primary install target, and `./scripts/install.sh` writes there by default.

**Claude Code is the one holdout.** It reads only `~/.claude/skills/`, `.claude/skills/`, and installed plugins. It gets its own native channel instead — the plugin marketplace in this repo, which is strictly better there: versioned installs, one-command updates, and the ability to bundle agents, hooks and MCP servers alongside the skill.

```
/plugin marketplace add itqanlab/agent-toolkit
```

`./scripts/install.sh --claude` is the fallback for anyone who would rather copy into `~/.claude/skills/` than register a marketplace. It installs the skill folder as a plain skill, which is all a single skill needs. The marketplace remains the route for updates and for anything that later bundles more than a skill.

## Codex

Measured on 2026-09-20 and 2026-09-21 with codex-cli 0.150.0, in a throwaway `CODEX_HOME`. Two commands make this possible without calling a model. `codex debug prompt-input` prints exactly what the model is shown, and `codex sandbox` runs a command under the sandbox. Run the tests again after a Codex upgrade.

**Two ways in. Both work.**

```
codex plugin marketplace add itqanlab/agent-toolkit      # then: codex plugin add <name>@itqan
./scripts/install.sh                                     # the neutral path, ~/.agents/skills
```

A plain `add` from real GitHub, with no `--ref` and no `--sparse`, offered all seven plugins. All seven installed at the right versions and reached the model. The neutral install and a project's `.agents/skills` worked the same way.

**Why every item is a plugin folder.** A Codex plugin must keep its skills in `skills/<name>/`. Codex's own validator says the manifest's `skills` field "must resolve to `skills`". A `SKILL.md` at the top of a plugin cannot work with any manifest value. We tried `./`, `.` and `./skills/`. Before this layout, `codex plugin add` reported "installed, enabled" while the model saw nothing. The alternatives all cost something: generated copies double every change on `main`, a generated branch needs `--ref`, committed symlinks break on Windows checkouts, and one big plugin removes per-skill install. So each item lives at `plugins/<name>/` with its skill folder inside. There is one source and no copies.

**What is generated.** `.agents/plugins/marketplace.json` is the catalog Codex reads first. Each plugin's `.codex-plugin/plugin.json` carries the `interface` block Codex shows on the plugin card. `npm run catalog` writes both from the skill's own data, and `validate.sh` fails if they drift. Each manifest also passes Codex's own validator, which `validate.sh` runs when Codex is installed.

**Updating.** For a git marketplace, run `codex plugin marketplace upgrade itqan`, then `codex plugin add <name>@itqan`. Re-adding installed the newer version, and Codex removed the old version folder from its cache. Start a new session afterwards. `codex plugin marketplace upgrade` works only on a git marketplace. On a local folder it says so and stops.

**The skill list and the display name.** Codex reads an optional `agents/openai.yaml` in the skill folder, and without it the skill has no display name, short line or starter prompt in its list. Tested through the app-server `skills/list` call, on the plugin route and the neutral path. Both showed the values. The file is generated from the skill's own data, so nothing is written twice. Its `policy.allow_implicit_invocation: false` also removes a skill from what the model is shown. We do not set it.

**How much description Codex shows the model.** Measured with skills that use our real descriptions. Codex gives the skill list a budget of about 23,200 characters. Below that, every description is shown in full. Above it, every description is shortened by the same amount, **from the end**, and the skill names always stay. It is about 20 skills at 766 characters each, then 446 characters each at 40 skills, and about 190 at 80. Our descriptions used to end with the trigger phrases, so at 40 installed skills only 8% of the phrases were visible. Now a description leads with one short sentence, then the trigger phrases, then the detail. At 40 skills 95% stay visible, and at 80 skills 34% do. `validate.sh` warns when the phrases start later than character 200. Only installed skills count, so a catalog of 100 is fine. The limit matters to someone who installs dozens.

**Other plugin sources.** Besides `local`, Codex accepts `git-subdir` and `npm`. A `git-subdir` entry installed our `watch-video` plugin straight from `plugins/watch-video` in this repository, and the model saw it. So another marketplace can list one of our plugins without copying it. An `npm` entry started npm, and failed only because the test package did not exist. An unknown source type is ignored without an error. We use `local`.

**Codex plugins also carry more than skills.** A plugin can bundle `.mcp.json` (MCP servers) and `.app.json` (connectors). When those join this catalog, they go in the same plugin folder.

**The sandbox blocks most of our skills until you allow two things.** With no config, a Codex session is `read-only` with the network restricted. In the usual `workspace-write` mode the network is still off, and writes outside the workspace are blocked. That includes the credential store, `~/.itqan-agent-toolkit`, or the path in `AGENT_TOOLKIT_HOME`. Skills that call a web API, or save a credential, fail without these lines in `~/.codex/config.toml`:

```toml
sandbox_mode = "workspace-write"

[sandbox_workspace_write]
network_access = true
writable_roots = ["/home/you/.itqan-agent-toolkit"]
```

`install.sh` and `install.ps1` print this, with your real path, when they find Codex. They never edit your config. Three details from the tests:

- `sandbox_mode` must be there. With only the two settings under `[sandbox_workspace_write]`, the session stayed read-only with no network.
- `/tmp` is writable by design in `workspace-write`, so a test that writes under `/tmp` proves nothing.
- The credential folder does not have to exist before you list it.

**Not checked.** Codex on Windows. Nothing here has run on a real Windows machine, so `.github/workflows/compat.yml` runs the Codex install, the PowerShell installer and the line-ending checks on Windows, macOS and Linux runners. Until that workflow has passed on Windows, treat Codex on Windows as unverified.

## Claude Code

The same folders work in Claude Code, and it was tested from real GitHub too. `claude plugin marketplace add itqanlab/agent-toolkit` and `claude plugin install watch-video@itqan` both worked, and `claude plugin details` listed the skill.

Two things differ from a plain skill folder, and both are measured:

- **The name has the plugin in front.** Installed as a plugin, the skill is `watch-video:watch-video` and the slash command is `/watch-video:watch-video`. A copy in `~/.claude/skills`, which `./scripts/install.sh --claude` makes, keeps the plain name. Asking in words is unaffected, because the agent picks a skill from its description.
- **Old versions stay in the cache.** After `claude plugin update`, both the old and the new version folder were on disk. Codex removes the old one. `toolkit-updates` only checks the newest.

## Other tools that read skills

`npx skills add itqanlab/agent-toolkit --list` found all seven skills in the nested layout, and `--skill watch-video` installed one into `./.agents/skills/`. So indexes that scan a repository for `SKILL.md` folders still find them.

## Windows

A simulated Windows checkout found a real bug. Git for Windows checks files out with CRLF line endings by default. Our parsers split on `\n`, so every frontmatter value came out empty, the generator refused to build, and the update checker would have read the version as `1.2.0\r`. Two fixes went in. `.gitattributes` keeps every file LF on every machine, and the parsers and the generator now read CRLF as LF anyway, for a download that never went through Git. A `.sh` file with CRLF still cannot run, which is why the attribute matters. The simulation is not a real Windows run. `.github/workflows/compat.yml` is.

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
