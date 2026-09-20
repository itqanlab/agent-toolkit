# Changelog

Latest: https://agent-toolkit.itqanlab.com/s/dokploy-ops/CHANGELOG.md

What changed in `dokploy-ops`, newest version first. To see if a newer version exists, open the address above and compare its top version with the one installed. Entries for versions before 1.1.0 were rebuilt from the git history.

## [1.2.0] - 2026-09-20

### Added

- Can be installed as a Codex plugin, from the same source as everything else.

### Changed

- The changelog address now points to the site, so it keeps working if the repository layout changes.
- Installed as a Claude Code plugin, the slash command is now `/dokploy-ops:dokploy-ops`, with the plugin name in front. Asking in words works as before, and a copy in a skills folder keeps the plain name `/dokploy-ops`.

## [1.1.0] - 2026-09-20

### Added

- This changelog, so you can see what changed in each version.
- An Updates section in `SKILL.md`. It tells the agent how to check for a newer version, and to report what changed before it updates.

## [1.0.0] - 2026-08-15

### Added

- Connect one or more self-hosted Dokploy installations. Each one is kept apart by name, so a deploy cannot land on the wrong server.
- See every app, database and compose stack with its real state.
- Deploy, and wait for the build to finish.
- Read logs, restart and stop services.
- Check domains and environment variables.
- Adopt a key the machine already has.
