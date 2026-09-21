# Changelog

Latest: https://agent-toolkit.itqanlab.com/s/hetzner-ops/CHANGELOG.md

What changed in `hetzner-ops`, newest version first. To see if a newer version exists, open the address above and compare its top version with the one installed. Entries for versions before 1.1.0 were rebuilt from the git history.

## [2.1.0] - 2026-09-21

### Added

- The tool has its own icon, in a dark and a light version. Codex shows it on the plugin card and in the skill list, and the toolkit site shows it on the tool's page and in share previews.

## [2.0.0] - 2026-09-21

### Breaking

- Installed as a Claude Code plugin, the slash command is now `/hetzner-ops:hetzner-ops`, with the plugin name in front. This has been true since 1.2.0, and this release marks it as breaking. Use the new name, or ask in words, which works as before. A copy in a skills folder keeps the plain name `/hetzner-ops`.

### Added

- Codex now shows a display name, a short line and a starter prompt for the skill in its skill list. They come from a generated `agents/openai.yaml` inside the skill folder. Other agents ignore that file.

### Changed

- The description now leads with what the skill does, then its trigger phrases, then the detail. Codex shortens long skill lists from the end, so the phrases that route a request now survive far longer. With 40 skills installed, 95% of the phrases stay visible instead of 8%.

## [1.2.0] - 2026-09-20

### Added

- Can be installed as a Codex plugin, from the same source as everything else.

### Changed

- The changelog address now points to the site, so it keeps working if the repository layout changes.

## [1.1.0] - 2026-09-20

### Added

- This changelog, so you can see what changed in each version.
- An Updates section in `SKILL.md`. It tells the agent how to check for a newer version, and to report what changed before it updates.

## [1.0.0] - 2026-08-15

### Added

- Connect one or more Hetzner Cloud projects. Each one is kept apart by name.
- List, create, start, stop, resize and delete servers.
- Manage SSH keys, firewalls, volumes and private networks.
- Manage DNS zones and records.
- Show what the project is costing.
- Adopt a token the machine already has.
