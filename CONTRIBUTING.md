# Contributing

## Setup

```bash
npm install          # installs husky hooks
```

## Commit format

```
<emoji> <type>(<scope>): <subject>
```

Emoji first so `git log --oneline` scans visually; the rest is Conventional Commits so tooling still parses it. Enforced by commitlint via a `commit-msg` hook.

| Emoji | Type | Use for |
| :-: | :-- | :-- |
| ✨ | `feat` | A new skill, or a new capability in an existing one |
| 🐛 | `fix` | Bug fix |
| 📝 | `docs` | Documentation only |
| 💄 | `style` | Formatting, no behaviour change |
| ♻️ | `refactor` | Restructuring without changing behaviour |
| ⚡ | `perf` | Performance |
| ✅ | `test` | Tests and validation |
| 📦 | `build` | Dependencies, packaging, workspaces |
| 👷 | `ci` | CI configuration |
| 🔧 | `chore` | Tooling, hooks, housekeeping |
| ⏪ | `revert` | Reverting a previous commit |

Rules: lowercase type, kebab-case scope, no capitalised subject, no trailing full stop, header ≤ 100 chars. Scope is usually the skill name (`watch-video`) or the area (`install`, `compat`, `hooks`).

```
✨ feat(watch-video): add --lang flag for non-English captions
🐛 fix(install): keep .claude-plugin when target is ~/.claude/skills
📝 docs(compat): record verified discovery paths for eight agents
```

## Hooks

| Hook | Runs |
| :-- | :-- |
| `pre-commit` | `scripts/validate.sh`, Claude manifest validation, `shellcheck` when installed |
| `commit-msg` | commitlint |

Both are installed by `npm install`. Bypass only when you mean it: `git commit --no-verify`.

## Adding a skill

Full rules in [docs/AUTHORING.md](docs/AUTHORING.md). The mechanical bar:

```bash
./scripts/validate.sh <name>
```

That checks the spec's `name` and `description` rules, that the frontmatter name matches the directory name, that every referenced script exists and is executable, that versions agree between `plugin.json` and `marketplace.json`, and that no vendor-specific variable or absolute path has crept into `SKILL.md`. It also runs the upstream reference validator from the spec authors when `uv` is installed.

Before opening a PR, install the skill and actually run it:

```bash
./scripts/install.sh <name> --link --force
```

## What does not belong here

Anything coupled to a private brand, account, or path. If a skill needs project-specific config, it reads that config from the host project at run time and documents the contract — it never assumes a directory that only exists on one machine.
