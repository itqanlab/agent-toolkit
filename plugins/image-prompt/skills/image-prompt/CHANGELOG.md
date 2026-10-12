# Changelog

Latest: https://agent-toolkit.itqanlab.com/s/image-prompt/CHANGELOG.md

What changed in `image-prompt`, newest version first. To see if a newer version exists, open the address above and compare its top version with the one installed.

## [1.0.1] - 2026-10-13

### Fixed

- Running scripts/prompt.mjs through a symlinked install now works. Before, it exited without writing anything.

## [1.0.0] - 2026-10-13

### Added

- Write an image prompt in the project's brand, from a brand file the project owns. No brand file is fine.
- Four directions: editorial, clean studio, detail and an overlay with room for a headline.
- Exact sizes for product pages, Instagram, Facebook, LinkedIn, X, Pinterest and YouTube thumbnails.
- A JSON beside each prompt with the size, ratio, don't list and a suggested Higgsfield model, with the crop needed when a model cannot make the exact ratio.
- Short paste steps for any web image tool.
- A prompt log per project that stops the same prompt being written twice.
