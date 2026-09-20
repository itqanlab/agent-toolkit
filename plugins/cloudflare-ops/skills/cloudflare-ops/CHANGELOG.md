# Changelog

Latest: https://agent-toolkit.itqanlab.com/s/cloudflare-ops/CHANGELOG.md

What changed in `cloudflare-ops`, newest version first. To see if a newer version exists, open the address above and compare its top version with the one installed. Entries for versions before 1.1.0 were rebuilt from the git history.

## [1.2.0] - 2026-09-20

### Added

- Can be installed as a Codex plugin, from the same source as everything else.

### Changed

- The changelog address now points to the site, so it keeps working if the repository layout changes.
- Installed as a Claude Code plugin, the slash command is now `/cloudflare-ops:cloudflare-ops`, with the plugin name in front. Asking in words works as before, and a copy in a skills folder keeps the plain name `/cloudflare-ops`.

## [1.1.0] - 2026-09-20

### Added

- This changelog, so you can see what changed in each version.
- An Updates section in `SKILL.md`. It tells the agent how to check for a newer version, and to report what changed before it updates.

## [1.0.0] - 2026-08-11

### Added

- Connect a Cloudflare account in two steps. The token needs three checkboxes and is never typed into the chat.
- Manage DNS records and subdomains.
- Publish a Pages site from start to finish, with a custom domain.
- Deploy a Worker and route a hostname to it.
- Manage R2 buckets.
- Look up any Cloudflare API endpoint instead of guessing at it.
- Declare the Node requirement, and offer to install Node when it is missing.
