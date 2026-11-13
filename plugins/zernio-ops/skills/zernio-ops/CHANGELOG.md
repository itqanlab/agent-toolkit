# Changelog

Latest: https://agent-toolkit.itqanlab.com/s/zernio-ops/CHANGELOG.md

What changed in `zernio-ops`, newest version first. To see if a newer version exists, open the address above and compare its top version with the one installed.

## [1.0.0] - 2026-11-13

### Added

- One MCP server, `zernio`, in front of every Zernio workspace. It exposes Zernio's tools once, adds an optional `workspace` argument to each, and finds the workspace from `account_id` when it is left out. `accounts_list` with no workspace lists them all.
- The workspaces are the `ZERNIO_KEY_<NAME>` lines in the toolkit's credential store. There is no fixed count, and a name can be a letter or a word. A new workspace is one new line and a restart.
- `scripts/setup.mjs` adds a key line for the person to fill in, checks each key against Zernio without printing it, and records the working workspaces in `state/setup.json`.
