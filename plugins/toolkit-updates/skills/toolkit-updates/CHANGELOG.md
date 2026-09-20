# Changelog

Latest: https://agent-toolkit.itqanlab.com/s/toolkit-updates/CHANGELOG.md

What changed in `toolkit-updates`, newest version first. To see if a newer version exists, open the address above and compare its top version with the one installed.

## [1.0.0] - 2026-09-20

### Added

- Check every toolkit skill installed on the machine against the public update feed, and list what changed in each newer version.
- Finds copies in the folders agents read, in a project, in Claude Code's plugin cache, and behind symlinks.
- Marks a breaking change, and gives the exact update command for each copy.
- Read-only. Exit code 10 means an update is available, and 2 means the feed could not be read.
- Optional `--available` lists toolkit skills that are not installed yet, and `--json` gives structured output.
