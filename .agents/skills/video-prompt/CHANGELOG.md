# Changelog

Latest: https://agent-toolkit.itqanlab.com/s/video-prompt/CHANGELOG.md

What changed in `video-prompt`, newest version first. To see if a newer version exists, open the address above and compare its top version with the one installed.

## [1.0.1] - 2026-10-13

### Fixed

- Running scripts/prompt.mjs through a symlinked install now works. Before, it exited without writing anything.

## [1.0.0] - 2026-10-13

### Added

- Write a short video prompt in the project's brand, from a brand file the project owns. No brand file is fine.
- Five shots: turntable, hero reveal, editorial, detail, and animating an existing photo.
- Sizes and accepted lengths for Reels, Stories, TikTok, YouTube, Shorts, LinkedIn, Facebook and product pages. A length a platform refuses is refused here too.
- A JSON beside each prompt with size, ratio, length and a suggested Higgsfield model, a cheaper draft model, and how many clips a longer piece needs.
- Short paste steps for any web video tool.
- A prompt log per project that stops the same prompt being written twice.
