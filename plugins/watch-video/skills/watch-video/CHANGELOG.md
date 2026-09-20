# Changelog

Latest: https://agent-toolkit.itqanlab.com/s/watch-video/CHANGELOG.md

What changed in `watch-video`, newest version first. To see if a newer version exists, open the address above and compare its top version with the one installed. Entries for versions before 1.2.0 were rebuilt from the git history.

## [1.3.0] - 2026-09-20

### Added

- Can be installed as a Codex plugin, from the same source as everything else.

### Changed

- The changelog address now points to the site, so it keeps working if the repository layout changes.

## [1.2.0] - 2026-09-20

### Added

- This changelog, so you can see what changed in each version.
- An Updates section in `SKILL.md`. It tells the agent how to check for a newer version, and to report what changed before it updates.

## [1.1.1] - 2026-08-11

### Changed

- The docs now say which platforms it runs on: macOS and Linux, and Windows through WSL or Git Bash.

## [1.1.0] - 2026-08-11

### Added

- A setup wizard that checks for ffmpeg and yt-dlp and installs them.
- Automatic transcription when a source has no captions.
- An optional free local engine for transcripts that runs offline.

### Fixed

- Playlists and audio-only sources are handled.

## [1.0.0] - 2026-08-11

### Added

- Watch a video from a URL or a local file. It pulls captions and extracts frames the agent can read.
