# Changelog

Latest: https://agent-toolkit.itqanlab.com/s/higgsfield-studio/CHANGELOG.md

## [1.1.0] - 2026-10-13

### Added

- A project can pin the Higgsfield account in .higgsfield/config.json (or HF_ACCOUNT). A paid job on any other signed-in account is refused before it runs, since the login is machine-wide and a free account looks just like the paid one.
- The reserve can be set per project in the same file.
- create no longer waits inside the CLI. It saves the job id at once and polls with a deadline (--timeout, 900 s by default). If it stops early, running the same command again picks the job up without paying again.

### Fixed

- Paid jobs run one at a time per project, so two jobs started together no longer count each other's charges.
- A fresh sign-in with no billing workspace selected now says how to pick one.
- Running scripts/hf.mjs through a symlinked install now works. Before, it exited without doing anything.

## [1.0.0] - 2026-10-12

### Added

- Make images, video, audio and 3D with Higgsfield from the agent, through Higgsfield's own command line tool.
- Every paid job is priced by Higgsfield before it runs, refused above `--max` or below the reserve, and never paid for twice.
- Each job's real cost is read from Higgsfield's transaction list and written to a ledger in the project.
- Product photoshoots and marketplace cards are planned and priced for free before any image is made.
- Deploying or publishing a website, training a Soul and changing the billing workspace need the user's yes.
- Seven more skills in the plugin, built on Higgsfield's official ones: Soul ID, product photoshoot, marketplace cards, brand kit, YouTube thumbnails, video explainers and websites.
