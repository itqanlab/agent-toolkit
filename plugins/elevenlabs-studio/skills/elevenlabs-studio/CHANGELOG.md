# Changelog

Latest: https://agent-toolkit.itqanlab.com/s/elevenlabs-studio/CHANGELOG.md

What changed in `elevenlabs-studio`, newest version first. To see if a newer version exists, open the address above and compare its top version with the one installed.

## [1.2.0] - 2026-10-13

### Added

- A free check of a finished take: the median pitch against an expected range, and every word of the script heard back by a local transcriber. Exit code 5 means redo the line. Arabic is compared without diacritics, and --dialect eg also accepts Egyptian qaf spoken as a glottal stop.

### Fixed

- Running scripts/eleven.mjs through a symlinked install now works. Before, it exited without doing anything.

## [1.1.0] - 2026-10-12

### Added

- Transcribe a recording or a link, with speaker labels, word timings and a list of names to spell right.
- Change the voice in a recording and keep the performance. Can clean the noise in the same call.
- Remove background noise and music from a recording.
- Dub a video or audio file into another language, in voices cloned from the speakers. An interrupted dub resumes instead of paying twice.
- Support for `eleven_v4`, ElevenLabs' newest voice model. Measured at about 0.11 credits per character, a quarter of `eleven_v3`.

### Changed

- Voice-over now uses `eleven_v4` by default, as ElevenLabs does. Pass `--model eleven_v3` for the old default.
- Calls priced by the length of a recording refuse to run when the length is unknown. Install ffmpeg, or pass `--seconds`.

## [1.0.0] - 2026-10-05

### Added

- Connect an ElevenLabs account through a guided setup. The key is pasted into a file, never into the chat.
- Make voice-over with any voice, with per-character timing for cutting a picture, and with neighbouring lines passed along so separate takes sound like one read (on models that support it).
- Make sound effects at an exact length, including loops that repeat without a gap.
- Make music from a prompt or from a composition plan. Plans are free, and the default model holds each section to its length.
- List voices and save their preview samples for free, to choose a voice by ear.
- See the plan, the credits left and the reset date.
- Every paid call is estimated first, served from a cache when it was already paid for, measured after, and written to a ledger in the project. Voice-over cost is measured exactly from ElevenLabs' history. A reserve refuses any call that would leave too few credits.
