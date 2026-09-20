# Authoring rules

A skill belongs in this repo only if a stranger can install it, under any conformant agent, and have it work. That is the whole bar. Everything below is a consequence of it.

The format is the [Agent Skills open standard](https://agentskills.io/specification), stewarded by the Agentic AI Foundation. Write to the spec, not to any one vendor.

## The agnostic checklist

**Relative paths only.** The spec says file references are relative to the skill root: `scripts/watch.sh`, `references/REFERENCE.md`. Never an absolute path, never `~/.claude/...`, and never a vendor variable like `${CLAUDE_PLUGIN_ROOT}` — that resolves in Claude Code and nowhere else.

**No vendor-specific instructions in the body.** The `SKILL.md` body is read verbatim by every agent. Do not name a specific tool's UI, slash command, or config file in it. Vendor packaging belongs in `.claude-plugin/plugin.json` and the marketplace entry, which other agents ignore.

**No personal or brand identifiers.** No account names, store handles, domain names, platform IDs, ticket boards, or persona names in the skill body. If the skill needs one, it reads it from the host project at run time and says so.

One deliberate exception: **the name of a directory this toolkit owns on disk.** A shared store — `~/.itqan-agent-toolkit/`, written by `toolkit-credentials` — carries the publisher prefix because it must not collide with another project's. `agent-toolkit` alone is a generic phrase, and two unrelated tools quietly sharing one credential directory is a bad failure to debug. This is the same reasoning as a scoped package name or a reverse-DNS bundle id, and it is the opposite of the coupling this rule exists to prevent: it hard-codes nothing about our accounts, projects or infrastructure, it only makes the folder unique and attributable. Any such path must still be overridable by an environment variable, so an organisation can relocate it.

**No private config contracts.** A skill requiring `{PROJECT_BRAND}` or `~/.claude/<org>-brand/identity.md` to exist is not agnostic. Either it works with no config, or it documents an explicit config file the host project supplies and degrades gracefully when that is absent.

**No required secrets** unless the skill's entire purpose is that service. `watch-video` needs no key; a Shopify skill obviously needs a Shopify connection, which is fine when documented and when it fails with a clear message.

**Fail loudly and usefully.** Every external binary gets a `command -v` check with an install hint for at least macOS and Debian/Ubuntu.

**Cross-platform where cheap.** Prefer POSIX shell. If a script is macOS-only (`sips`, `osascript`, `pbcopy`), declare it in `compatibility` rather than failing mysteriously on Linux.

**Deterministic outputs.** Write to a temp dir by default, allow `--outdir`. Never write into the user's project without being told to.

## Frontmatter

Per the spec, `name` and `description` are required; `license`, `compatibility`, `metadata`, and `allowed-tools` are optional.

- `name` — 1–64 chars, lowercase alphanumerics and hyphens, no leading/trailing hyphen, no consecutive hyphens, and it **must match the parent directory name**.
- `description` — up to 1024 chars. This is the only thing an agent sees when deciding whether to invoke the skill, so it must carry the trigger phrases a user would actually type. Write it as: what it does, what it needs, then explicit `Triggers: '...', '...'`. **Quote the whole value** — `description: "… Triggers: 'a', 'b'"` — because the colon in `Triggers:` inside a bare scalar is invalid YAML and the upstream validator rejects it. Use single quotes for the phrases so the outer double quotes stay valid. The generated site leads each skill page with these phrases, so a skill without them loses its most useful section.
- `compatibility` — use it when the skill needs system packages or network access. Most skills do not need it.

Keep the body under 500 lines and roughly under 5000 tokens; push detail into `references/`, which agents load only on demand.

## Adding a skill

1. `mkdir -p skills/<name>/scripts`
2. Write `skills/<name>/SKILL.md`. The frontmatter `name` must match `<name>`. Under `metadata:` set `version` and `category`. The category must be one of the ids in `catalog/categories.json`.
3. Write `skills/<name>/README.md`: what it does, requirements, usage, an example
4. Write `skills/<name>/.claude-plugin/plugin.json`. Give it `name`, `version`, `description`, `author`, `license`, `keywords` and a `homepage` of `https://github.com/itqanlab/agent-toolkit/tree/main/skills/<name>`. The `version` must equal `metadata.version` in `SKILL.md`.
5. Write `skills/<name>/CHANGELOG.md`, and add the Updates section to `SKILL.md` (see Changelog below).
6. Run `npm run catalog`. It writes the entry in `.claude-plugin/marketplace.json` and the row in the root `README.md` table. Do not edit those two by hand. The next run would overwrite you, and `validate.sh` fails while they are out of date.
7. Validate and actually run it:
   ```bash
   ./scripts/validate.sh <name>              # spec, portability rules, and the catalog check
   claude plugin validate skills/<name>
   claude plugin validate .
   ./scripts/install.sh <name> --link --force
   ```

`scripts/validate.sh` enforces every rule above that can be checked mechanically, and exits non-zero on failure. It is the gate; run it before every push. The eight agents it protects against are listed in [COMPATIBILITY.md](COMPATIBILITY.md).

The `metadata.pluginRoot` shorthand for marketplace sources is documented upstream but is rejected by `claude plugin validate`, so use the explicit `./skills/<name>` path.

Plugin manifests cannot reference paths containing `..` — the validator blocks it as path traversal. That is precisely why the skill directory and the plugin directory are the same directory.

## Changelog

Every item keeps a `CHANGELOG.md` next to its manifest. It is written for people and read by agents. An agent that has the item installed can read its own history from the folder. Then it can open the address on the `Latest:` line, see if a newer version exists, and tell the user exactly what changed before it updates.

The format is strict on purpose, so it can be parsed without guessing:

```markdown
# Changelog

Latest: https://raw.githubusercontent.com/itqanlab/agent-toolkit/main/skills/<name>/CHANGELOG.md

## [1.2.0] - 2026-09-20

### Added

- One line per change. Say what the user can now do.

### Fixed

- Another line.
```

Rules the generator enforces:

- Newest version first. Each heading is `## [x.y.z] - YYYY-MM-DD` with a real date.
- Sections are `Breaking`, `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`. Nothing else.
- Every release has at least one change.
- The newest entry must equal the item's version in `plugin.json` and `metadata.version`. So a version bump without an entry fails.
- The `Latest:` line must be the raw address of this same file on `main`.
- `SKILL.md` must mention `CHANGELOG.md`. Copy the "Updates" section from any existing skill.

Use `### Breaking` whenever the user has to do something after updating: run a command, change a setting, or re-connect an account. The site and the feed mark those releases.

Which number to bump: a new capability is a minor version, a fix is a patch, and anything that breaks existing use is a major version.

The site turns these files into `/updates/` for people and `/updates.json` for agents. Each skill page also gets its own `changelog.json`.

## Other kinds of items

Today the catalog holds skills. It is meant to hold more: MCP servers, connectors and bundles. Two rules keep that possible.

- Every kind of item keeps its own `CHANGELOG.md` and version, with the same format and the same checks.
- Anything shipped for Codex lives in `plugins/<name>/` with a `.codex-plugin/plugin.json`. Codex plugins are how it bundles skills with `.mcp.json` and `.app.json` files. See [COMPATIBILITY.md](COMPATIBILITY.md#codex).

The generator and the site only walk `skills/` today. Adding a new kind means teaching them one more folder. The changelog parser in `scripts/lib/changelog.mjs` does not care what the item is.

## Categories, and leading the home page

Categories come from one list, `catalog/categories.json`. Each entry has an `id`, a `label` and a one-line `description`. To add a category, add an entry to that list. A skill uses it by setting `metadata.category` to the id. The generator rejects any id that is not in the list, so a typo cannot create a new category by accident.

The site shows a filter and a page for every category that has at least one skill. An empty category shows nothing.

To put a skill first on the home page, set `featured: "true"` under `metadata:` in its `SKILL.md`. Featured skills come first. The rest fill the six places in name order.

## Choosing where a component goes

| You have | Put it in |
| :-- | :-- |
| One skill, scripts only | `skills/<name>/` |
| Several related skills | `plugins/<name>/skills/` |
| A skill plus a subagent, hook, or command | `plugins/<name>/` |
| An MCP server users install via `/plugin` | `plugins/<name>/` with `.mcp.json` |
| A standalone MCP server published to npm | `mcp/<name>/` |

Default to `skills/<name>/`. A single-skill plugin puts `SKILL.md` at the plugin root, which is what makes one directory serve both the open standard and Claude Code — it stays a valid Agent Skills directory that all eight agents can read.

Move to `plugins/<name>/` only when the bundle needs components the standard has no concept of. Subagents, hooks and commands are **Claude Code specific**; other agents ignore them entirely. So express a capability as a skill whenever instructions plus a script can do the job, and reserve Claude-only components for things that genuinely cannot be — a hook that must fire on a tool event, or a subagent that needs its own context window.

Note that `scripts/install.sh` only walks `skills/` at the repo root. A skill bundled inside `plugins/<name>/skills/` is therefore not installed for other agents automatically, which is another reason to keep portable skills at the top level.

## Versioning

Bump `version` in `plugin.json` and in the skill's `metadata.version` when behavior changes, add the matching entry to `CHANGELOG.md`, then run `npm run catalog`. Claude Code only ships an update when that string changes. The generator refuses to run if the two versions differ, or if the changelog does not start with that version.

Breaking a flag, renaming a skill, or changing output layout is a major bump. When renaming or removing a plugin, add the old name to the `renames` map in `.claude-plugin/marketplace.json`, so existing installs migrate instead of breaking. The generator only rewrites the `plugins` list. Every other key in that file is kept, including `renames`.
