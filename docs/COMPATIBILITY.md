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
| OpenCode 1.18.31 | 7 of 7 in `opencode debug skill`, if the output goes to a file. See below | None used |
| GitHub Copilot CLI 1.0.86 | 7 of 7 in `copilot skill list` | `copilot plugin marketplace add itqanlab/agent-toolkit`: lists all 7, installed one |
| Amp 0.0.1789934445 | 7 of 7 in `amp skills list`. Its own 12 built-in skills were the only ones in the control | `amp skills add itqanlab/agent-toolkit/plugins/<name>/skills/<name>`: installed `watch-video` from GitHub. **`amp skills add itqanlab/agent-toolkit` finds nothing.** See below |
| Goose 1.51.0 | 7 of 7 in `goose skills list`. The control showed only its two built-in skills. It also prints each skill's token cost | None used |
| Cursor | Not tested. Its command line keeps the login in the macOS keychain, which a scratch home cannot isolate, and it stopped at an existing login. It needs an API key | Not tested |

**OpenCode's debug output is cut when piped.** A first run listed 6 of 7 skills, and it looked like a discovery bug. It was not. `opencode debug skill` prints about 80,000 bytes, because it includes every skill's full text. When its output goes into a pipe, it stops at exactly 65,536 bytes, one pipe buffer, and leaves broken JSON. Which skills get cut depends on scan order. Fifteen runs on fresh homes reproduced it every time when piped, and never when written to a file, where all 7 are present. So OpenCode finds everything, and only its debug printer truncates. Redirect the output to a file when you test it. A tool that waits for the pipe, such as Python, prints 70,000 characters through a pipe without loss.

**Amp finds skills in `skills/`, `.agents/skills/`, `.claude/skills/`, the repository root and one level below it, and nowhere else.** Tested with small layouts. It does not look in `plugins/<name>/skills/<name>`, or three folders down. Our old `skills/<name>` layout was found, so moving to the plugin layout broke the whole-repository command `amp skills add itqanlab/agent-toolkit`. Adding by path still works, and so does the neutral folder. We keep the layout, because Codex requires it and a committed symlink would break on Windows. The `npx skills` tool and Gemini and Copilot are not affected.

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

**Other plugin sources.** Besides `local`, Codex accepts `git-subdir` and `npm`. A `git-subdir` entry installed our `watch-video` plugin straight from `plugins/watch-video` in this repository, and the model saw it. So another marketplace can list one of our plugins without copying it. An `npm` entry, written `{"source": "npm", "package": "@scope/name"}`, installed a real package as a plugin at the version in the package, and the model saw the skill. That was tested against a local registry, with nothing published. The package name must be a valid npm name. A file path is silently ignored. An unknown source type is also ignored without an error. We use `local`.

**What the plugin card shows.** Codex's app-server `plugin/list` call returns the fields a card is drawn from. For all seven plugins it returned the display name, the short line, the category, the capabilities, the developer, the site link and three starter prompts, exactly as generated. The desktop app reads the same call. Whether the app draws them correctly on screen was not checked, because it cannot be driven from here. One cosmetic point: starter prompts made from questions have no question mark.

**Codex plugins also carry more than skills.** A plugin can bundle `.mcp.json` (MCP servers) and `.app.json` (connectors). When those join this catalog, they go in the same plugin folder.

**The sandbox blocks most of our skills until you allow two things.** With no config, a Codex session is `read-only` with the network restricted. In the usual `workspace-write` mode the network is still off, and writes outside the workspace are blocked. That includes the credential store, `~/.itqan-agent-toolkit`, or the path in `AGENT_TOOLKIT_HOME`. Skills that call a web API, or save a credential, fail without these lines in `~/.codex/config.toml`:

```toml
sandbox_mode = "workspace-write"

[sandbox_workspace_write]
network_access = true
writable_roots = ["/home/you/.itqan-agent-toolkit"]
```

`install.sh` and `install.ps1` print this, with your real path, when they find Codex. They never edit your config. The Windows one adds two lines. See the Windows section below. The compatibility workflow takes the exact text each installer prints, writes it as a config file, and checks that Codex then reports a `workspace-write` session with the network on, on all three systems. Three details from the tests:

- `sandbox_mode` must be there. With only the two settings under `[sandbox_workspace_write]`, the session stayed read-only with no network.
- `/tmp` is writable by design in `workspace-write`, so a test that writes under `/tmp` proves nothing.
- The credential folder does not have to exist before you list it.

**Versions.** The local tests used Codex 0.150.0. The compatibility workflow installs the latest Codex from npm on each run, and it passed with 0.155.1 on Windows, macOS and Linux.

**Not checked.** How the desktop app draws the cards, and the Linux sandbox, which the workflow only reaches as far as the config Codex reports.

## Claude Code

The same folders work in Claude Code, and it was tested from real GitHub too. `claude plugin marketplace add itqanlab/agent-toolkit` and `claude plugin install watch-video@itqan` both worked, and `claude plugin details` listed the skill.

Two things differ from a plain skill folder, and both are measured:

- **The name has the plugin in front.** Installed as a plugin, the skill is `watch-video:watch-video` and the slash command is `/watch-video:watch-video`. A copy in `~/.claude/skills`, which `./scripts/install.sh --claude` makes, keeps the plain name. Asking in words is unaffected, because the agent picks a skill from its description.
- **Old versions stay in the cache.** After `claude plugin update`, both the old and the new version folder were on disk. Codex removes the old one. `toolkit-updates` only checks the newest.

## Other tools that read skills

`npx skills add itqanlab/agent-toolkit --list` found all seven skills in the nested layout, and `--skill watch-video` installed one into `./.agents/skills/`. So indexes that scan a repository for `SKILL.md` folders still find them.

## Windows

Checked on a real Windows runner (Windows Server 2025) by `.github/workflows/compat.yml`. Every step passed: the generated files match, the checkout is LF, the validator runs, a real Codex installs all seven plugins and shows them to the model, the PowerShell installer copies all seven skills, and the update checker finds the seven copies in Codex's plugin cache. The same workflow passes on macOS and Linux.

The run found two real bugs, and a simulated checkout found a third. A simulated Windows checkout found the first. Git for Windows checks files out with CRLF line endings by default. Our parsers split on `\n`, so every frontmatter value came out empty, the generator refused to build, and the update checker would have read the version as `1.2.0\r`. Two fixes went in. `.gitattributes` keeps every file LF on every machine, and the parsers and the generator now read CRLF as LF anyway, for a download that never went through Git. A `.sh` file with CRLF still cannot run, which is why the attribute matters. The second bug was found on the real runner. The Windows console defaults to cp1252, and the Python validator crashed printing a check mark, so it now writes UTF-8. The third was a mistake in the workflow's own test, not in the product: `Write-Host` output does not go through `2>&1`, so the installer's Codex text was captured with `*>&1`. On Windows the installer printed `writable_roots = ["C:/Users/.../.itqan-agent-toolkit"]`, a valid TOML path with forward slashes.

## The Codex sandbox on Windows

Measured on a real Windows runner with Codex 0.155.1. It works differently from macOS in four ways.

- **The `[windows]` line is required.** With only the settings above, a Windows session stayed `read-only` with the network restricted. Add `[windows]` and `sandbox = "elevated"`. Codex's own setup writes that line too. A hand-written line was enough on a fresh machine: the session became `workspace-write` with the network on, and writes to the store worked.
- **`elevated` enforces the network block and `unelevated` does not.** In `elevated` mode Node's `fetch` failed with `EACCES` until `network_access = true` was set. In `unelevated` mode it worked with no permission granted. On a fresh machine with a hand-written config and no setup, it also worked. Our skills only need the network allowed, so all of these work for them.
- **The credential folder must exist first.** Creating it inside the sandbox was denied even with the path listed. Once it existed and was listed, `cmd` and Node could both write to it. A folder that was not listed, and any other place, stayed blocked. On macOS the folder did not need to exist. `install.ps1` prints the command to create it.
- **`curl.exe` fails with a TLS error under the sandbox** (exit 35), even with the network allowed. Node's `fetch` works. Our skills use Node, so this only matters to a script that uses Windows curl.

`codex sandbox` ignores `sandbox_mode` from the config file on Windows too, so the direct tests pass it as a flag.

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
