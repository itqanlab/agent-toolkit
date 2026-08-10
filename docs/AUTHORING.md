# Authoring rules

A skill belongs in this repo only if a stranger can install it, under any conformant agent, and have it work. That is the whole bar. Everything below is a consequence of it.

The format is the [Agent Skills open standard](https://agentskills.io/specification), stewarded by the Agentic AI Foundation. Write to the spec, not to any one vendor.

## The agnostic checklist

**Relative paths only.** The spec says file references are relative to the skill root: `scripts/watch.sh`, `references/REFERENCE.md`. Never an absolute path, never `~/.claude/...`, and never a vendor variable like `${CLAUDE_PLUGIN_ROOT}` — that resolves in Claude Code and nowhere else.

**No vendor-specific instructions in the body.** The `SKILL.md` body is read verbatim by every agent. Do not name a specific tool's UI, slash command, or config file in it. Vendor packaging belongs in `.claude-plugin/plugin.json` and the marketplace entry, which other agents ignore.

**No personal or brand identifiers.** No account names, store handles, domain names, platform IDs, ticket boards, or persona names in the skill body. If the skill needs one, it reads it from the host project at run time and says so.

**No private config contracts.** A skill requiring `{PROJECT_BRAND}` or `~/.claude/<org>-brand/identity.md` to exist is not agnostic. Either it works with no config, or it documents an explicit config file the host project supplies and degrades gracefully when that is absent.

**No required secrets** unless the skill's entire purpose is that service. `watch-video` needs no key; a Shopify skill obviously needs a Shopify connection, which is fine when documented and when it fails with a clear message.

**Fail loudly and usefully.** Every external binary gets a `command -v` check with an install hint for at least macOS and Debian/Ubuntu.

**Cross-platform where cheap.** Prefer POSIX shell. If a script is macOS-only (`sips`, `osascript`, `pbcopy`), declare it in `compatibility` rather than failing mysteriously on Linux.

**Deterministic outputs.** Write to a temp dir by default, allow `--outdir`. Never write into the user's project without being told to.

## Frontmatter

Per the spec, `name` and `description` are required; `license`, `compatibility`, `metadata`, and `allowed-tools` are optional.

- `name` — 1–64 chars, lowercase alphanumerics and hyphens, no leading/trailing hyphen, no consecutive hyphens, and it **must match the parent directory name**.
- `description` — up to 1024 chars. This is the only thing an agent sees when deciding whether to invoke the skill, so it must carry the trigger phrases a user would actually type. Write it as: what it does, what it needs, then explicit `Triggers: '...', '...'`.
- `compatibility` — use it when the skill needs system packages or network access. Most skills do not need it.

Keep the body under 500 lines and roughly under 5000 tokens; push detail into `references/`, which agents load only on demand.

## Adding a skill

1. `mkdir -p skills/<name>/scripts`
2. Write `skills/<name>/SKILL.md` — frontmatter `name` identical to `<name>`
3. Write `skills/<name>/README.md` — what it does, requirements, usage, an example
4. Write `skills/<name>/.claude-plugin/plugin.json` (`name` is the only required field; fill the rest in for a decent marketplace listing)
5. Add an entry to `.claude-plugin/marketplace.json` with `"source": "./skills/<name>"`
6. Add a row to the table in the root `README.md`
7. Validate and actually run it:
   ```bash
   ./scripts/validate.sh <name>              # spec + portability rules
   claude plugin validate skills/<name>
   claude plugin validate .
   ./scripts/install.sh <name> --link --force
   ```

`scripts/validate.sh` enforces every rule above that can be checked mechanically, and exits non-zero on failure. It is the gate; run it before every push. The eight agents it protects against are listed in [COMPATIBILITY.md](COMPATIBILITY.md).

The `metadata.pluginRoot` shorthand for marketplace sources is documented upstream but is rejected by `claude plugin validate`, so use the explicit `./skills/<name>` path.

Plugin manifests cannot reference paths containing `..` — the validator blocks it as path traversal. That is precisely why the skill directory and the plugin directory are the same directory.

## Multi-skill plugins

A single-skill plugin puts `SKILL.md` at the plugin root, which is what makes one directory serve both the spec and Claude Code. If a plugin must ship several related skills, it needs a `skills/<skill-name>/` subdirectory instead, and the plugin root stops being a valid standalone skill directory. Prefer one skill per directory and accept that constraint only when the skills genuinely cannot stand apart.

## Versioning

Bump `version` in both `plugin.json` and the marketplace entry when behavior changes; Claude Code only ships an update when that string changes. Mirror it in the skill's `metadata.version`.

Breaking a flag, renaming a skill, or changing output layout is a major bump. When renaming or removing a plugin, add the old name to the marketplace `renames` map so existing installs migrate instead of breaking.
