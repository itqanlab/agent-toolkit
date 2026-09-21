# Changelog

Latest: https://agent-toolkit.itqanlab.com/s/toolkit-updates/CHANGELOG.md

What changed in `toolkit-updates`, newest version first. To see if a newer version exists, open the address above and compare its top version with the one installed.

## [2.1.0] - 2026-09-21

### Added

- The tool has its own icon, in a dark and a light version. Codex shows it on the plugin card and in the skill list, and the toolkit site shows it on the tool's page and in share previews.

## [2.0.0] - 2026-09-21

### Breaking

- Installed as a Claude Code plugin, the slash command is now `/toolkit-updates:toolkit-updates`, with the plugin name in front. This has been true since 1.1.0, and this release marks it as breaking. Use the new name, or ask in words, which works as before. A copy in a skills folder keeps the plain name `/toolkit-updates`.

### Added

- Codex now shows a display name, a short line and a starter prompt for the skill in its skill list. They come from a generated `agents/openai.yaml` inside the skill folder. Other agents ignore that file.

### Changed

- The description now leads with what the skill does, then its trigger phrases, then the detail. Codex shortens long skill lists from the end, so the phrases that route a request now survive far longer. With 40 skills installed, 95% of the phrases stay visible instead of 8%.

### Fixed

- A skill header with Windows line endings (CRLF) is read correctly, so the version is no longer misread on a Windows checkout.

## [1.1.0] - 2026-09-20

### Added

- Finds copies installed as Codex plugins, and gives the Codex update command for them.
- Finds Claude Code plugin copies in the newer layout, where the skill sits in a `skills/` folder. The older layout still works.
- Each line says where the copy lives, so a skill installed in two agents is easy to tell apart.
- Can be installed as a Codex plugin, from the same source as everything else.

### Changed

- Claude Code keeps old versions in its plugin cache after an update. Only the newest one is checked now, so an old folder is no longer reported as behind.
- The changelog address now points to the site, so it keeps working if the repository layout changes.

## [1.0.0] - 2026-09-20

### Added

- Check every toolkit skill installed on the machine against the public update feed, and list what changed in each newer version.
- Finds copies in the folders agents read, in a project, in Claude Code's plugin cache, and behind symlinks.
- Marks a breaking change, and gives the exact update command for each copy.
- Read-only. Exit code 10 means an update is available, and 2 means the feed could not be read.
- Optional `--available` lists toolkit skills that are not installed yet, and `--json` gives structured output.
