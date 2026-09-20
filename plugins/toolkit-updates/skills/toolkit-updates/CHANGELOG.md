# Changelog

Latest: https://agent-toolkit.itqanlab.com/s/toolkit-updates/CHANGELOG.md

What changed in `toolkit-updates`, newest version first. To see if a newer version exists, open the address above and compare its top version with the one installed.

## [1.1.0] - 2026-09-20

### Added

- Finds copies installed as Codex plugins, and gives the Codex update command for them.
- Finds Claude Code plugin copies in the newer layout, where the skill sits in a `skills/` folder. The older layout still works.
- Each line says where the copy lives, so a skill installed in two agents is easy to tell apart.
- Can be installed as a Codex plugin, from the same source as everything else.

### Changed

- Claude Code keeps old versions in its plugin cache after an update. Only the newest one is checked now, so an old folder is no longer reported as behind.
- The changelog address now points to the site, so it keeps working if the repository layout changes.
- Installed as a Claude Code plugin, the slash command is now `/toolkit-updates:toolkit-updates`, with the plugin name in front. Asking in words works as before, and a copy in a skills folder keeps the plain name `/toolkit-updates`.

## [1.0.0] - 2026-09-20

### Added

- Check every toolkit skill installed on the machine against the public update feed, and list what changed in each newer version.
- Finds copies in the folders agents read, in a project, in Claude Code's plugin cache, and behind symlinks.
- Marks a breaking change, and gives the exact update command for each copy.
- Read-only. Exit code 10 means an update is available, and 2 means the feed could not be read.
- Optional `--available` lists toolkit skills that are not installed yet, and `--json` gives structured output.
