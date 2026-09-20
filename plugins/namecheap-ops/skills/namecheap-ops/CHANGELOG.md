# Changelog

Latest: https://agent-toolkit.itqanlab.com/s/namecheap-ops/CHANGELOG.md

What changed in `namecheap-ops`, newest version first. To see if a newer version exists, open the address above and compare its top version with the one installed. Entries for versions before 1.1.0 were rebuilt from the git history.

## [1.2.0] - 2026-09-20

### Added

- Can be installed as a Codex plugin, from the same source as everything else.

### Changed

- The changelog address now points to the site, so it keeps working if the repository layout changes.

## [1.1.0] - 2026-09-20

### Added

- This changelog, so you can see what changed in each version.
- An Updates section in `SKILL.md`. It tells the agent how to check for a newer version, and to report what changed before it updates.

## [1.0.0] - 2026-09-20

### Added

- Connect one or more Namecheap accounts. Each one is kept apart by name.
- List domains, see what expires and what will not renew by itself, and check the balance.
- Look up nameservers and change them.
- Check whether a name is free, and see registration and renewal prices.
- Edit DNS records for domains that use Namecheap's own DNS.
- Handle Namecheap's address whitelist, including through an SSH server with a fixed address.
