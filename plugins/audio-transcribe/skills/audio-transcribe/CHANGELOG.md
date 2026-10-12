# Changelog

Latest: https://agent-toolkit.itqanlab.com/s/audio-transcribe/CHANGELOG.md

What changed in `audio-transcribe`, newest version first. To see if a newer version exists, open the address above and compare its top version with the one installed.

## [1.0.0] - 2026-10-13

### Added

- Transcribe a local audio or video file, a direct media link, or a YouTube or other site link, fully on this machine.
- Arabic (including Egyptian dialect), English, or automatic language detection.
- Plain text, SRT and VTT subtitles, or JSON with timings.
- Uses the fastest local Whisper engine installed: mlx-whisper on Apple Silicon, whisper-ctranslate2 or openai-whisper elsewhere.
- A model is never downloaded without first saying how big it is.
- Warns when the audio is near-silent, because Whisper invents text over silence.
- Retries once with the large model when the output falls into a repetition loop.
- A dependency check that shows the install commands and asks before running them, on macOS, Linux and Windows.
