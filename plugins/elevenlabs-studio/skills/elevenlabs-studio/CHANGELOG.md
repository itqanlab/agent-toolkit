# Changelog

Latest: https://agent-toolkit.itqanlab.com/s/elevenlabs-studio/CHANGELOG.md

What changed in `elevenlabs-studio`, newest version first. To see if a newer version exists, open the address above and compare its top version with the one installed.

## [1.0.0] - 2026-10-05

### Added

- Connect an ElevenLabs account through a guided setup. The key is pasted into a file, never into the chat.
- Make voice-over with any voice, with per-character timing for cutting a picture, and with neighbouring lines passed along so separate takes sound like one read (on models that support it).
- Make sound effects at an exact length, including loops that repeat without a gap.
- Make music from a prompt or from a composition plan. Plans are free, and the default model holds each section to its length.
- List voices and save their preview samples for free, to choose a voice by ear.
- See the plan, the credits left and the reset date.
- Every paid call is estimated first, served from a cache when it was already paid for, measured after, and written to a ledger in the project. Voice-over cost is measured exactly from ElevenLabs' history. A reserve refuses any call that would leave too few credits.
