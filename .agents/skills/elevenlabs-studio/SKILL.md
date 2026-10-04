---
name: elevenlabs-studio
description: "Make voice-over, sound effects and music with ElevenLabs, and spend the credits on purpose. Triggers: 'make a voice-over', 'read this script aloud', 'generate a sound effect', 'make background music', 'find a voice for this video', 'how many ElevenLabs credits are left', 'what have we spent on ElevenLabs', 'text to speech', 'elevenlabs'. Every paid call is priced first, never paid for twice, measured after, and written to a ledger in the project. A reserve stops a runaway loop from emptying the month. Needs an ElevenLabs API key, set up once through a guided flow without the key ever being typed into the chat. Works on macOS, Windows and Linux."
license: MIT
compatibility: "Requires Node 18 or newer. Run scripts/setup-deps.sh (or scripts/setup-deps.ps1 on Windows) to check for it and install it if missing. Needs network access to the ElevenLabs API and an ElevenLabs account. Generating audio spends that account's credits."
metadata:
  author: itqanlab
  version: 1.0.0
  category: media
  short: "Voice-over, sound effects and music, on a budget"
  starter: "make a voice-over for this script without wasting credits"
---

# ElevenLabs Studio

Voice-over (text to speech), sound effects and music from ElevenLabs. ElevenLabs is paid by the credit, so every call goes through one script, `scripts/eleven.mjs`, which prices the call before making it, never pays twice for the same request, and writes what each call really cost. Never call the ElevenLabs API any other way from this skill.

## Who you are doing this for

Assume the person asking has never opened a terminal. **You run the commands; they never do.** The one thing they do by hand is create a key on the ElevenLabs website and paste it into a file, so it never passes through the conversation.

Report in plain words: "the voice-over is in `vo/line-03.mp3`, it cost 64 credits, 41,200 are left." Do not make them read JSON. If they are clearly comfortable with a terminal, let them drive.

## Before anything else: check the dependencies

```
sh scripts/setup-deps.sh --check
```

Non-zero exit means Node is missing or older than 18. `sh scripts/setup-deps.sh` (Windows: `.\scripts\setup-deps.ps1`) prints the right install command for the machine and asks before running it; `--yes` skips the question.

## Connect an account first

```
node scripts/setup.mjs status
```

If ElevenLabs is not connected, run the guided setup and follow what it prints:

```
node scripts/setup.mjs begin
```

It creates an empty credential file and tells the user how to make the key. The key is created at https://elevenlabs.io/app/settings/api-keys with exactly these permissions switched on: **Text to Speech**, **Sound Effects**, **Music**, **Voices (read)** and **User (read)**. User read is what lets the tool read the credit balance. Without it every paid call is refused, because the tool will not spend what it cannot count. If the key form has a History row, set it to Read: that lets the tool measure each voice-over's exact cost.

**Never ask for the key in the conversation, and never display the credential file.** The user pastes the key into the file the script names. When they say they are done:

```
node scripts/setup.mjs finish
```

That checks the key with two free calls, reports the plan and credits left, and records when it was verified. `begin --force` replaces a saved key. The file and its location come from the shared credential convention, `toolkit-credentials`: `<store root>/credentials/elevenlabs.env`, where the store root is `AGENT_TOOLKIT_HOME`, or `.itqan-agent-toolkit` in the user's home folder.

## Commands

Free:

```
node scripts/eleven.mjs account                      plan, credits used and left, reset date
node scripts/eleven.mjs voices [--q calm] [--library] [--lang en] [--previews DIR]
node scripts/eleven.mjs plan --prompt "..." --ms 45000 --out plan.json [--model music_v1]
node scripts/eleven.mjs ledger                       what has been spent, by kind and by tag
```

Paid:

```
node scripts/eleven.mjs tts --voice ID --text "..." --out line.mp3 [--model eleven_v3]
     [--timestamps] [--prev "..."] [--next "..."] [--settings '{"stability":0.5}'] [--lang en] [--format mp3_44100_128]
node scripts/eleven.mjs sfx --text "..." --out hit.mp3 [--duration 2.5] [--influence 0.6] [--loop]
node scripts/eleven.mjs music (--plan plan.json | --prompt "..." --ms 45000) --out bed.mp3 [--model music_v1] [--instrumental]
```

Every paid command also takes `--dry` (print the estimate and the request, call nothing), `--max N` (refuse above N credits), `--fresh` (skip the cache, needs `--why`), `--tag NAME`, `--why "..."` and `--out FILE`.

- `voices --previews DIR` saves each voice's sample. Those are static files and cost nothing.
- `tts --timestamps` also writes `<out>.json`: the timing of every character, which is what a picture is cut to.
- `--prev` and `--next` pass the neighbouring lines, so separate takes sound like one read. `eleven_v3` does not support them yet, so the tool refuses them on that model. Stitch with `eleven_multilingual_v2`.
- `eleven_v3` can drift a voice away from its speaker: a male library voice came back female (median pitch 216 Hz, against 106 Hz for the same voice on `eleven_multilingual_v2`). Check the pitch of each take, and use `eleven_multilingual_v2` for a voice that drifts.
- `plan` is free according to ElevenLabs' own documentation. It is still measured, like everything else.
- `music` defaults to `music_v1` with `respect_sections_durations: true`. It is the only model that holds each section to its `duration_ms`. The v2 models ignore section lengths, so their music cannot be cut to a picture. Make the plan with the same model you render with, because the plan shape differs.

API detail (models, voice settings, output formats, the plan schema) is in `references/tts.md`, `references/music.md` and `references/sound-effects.md`. Read them when you need a field, not before. `references/ATTRIBUTION.md` credits the material adapted from ElevenLabs.

## How credits are protected

1. **Cache by request.** The cache key is a hash of the endpoint and the body. The same request returns the file already paid for, at 0 credits. `--fresh` is the only way past it, and it refuses to run without a reason in `--why`.
2. **Estimate before calling.** From a rate table: text to speech about 0.45 credits per character on `eleven_v3` and `eleven_multilingual_v2` (measured on a Creator plan; published was 1), flash and turbo about 0.25 (assumed, not measured), a sound effect about 11.2 per second when `--duration` is set (measured) or about 200 when the model picks the length (published), music about 825 per minute (measured; the published figure was 900), a plan free. These are estimates, not quotes.
3. **Measure after calling.** Text to speech is measured exactly, from the history item that matches the call's request id (free to read). Other calls fall back to the balance read before and after, which ElevenLabs settles a few seconds late, so the tool polls it for up to about 30 seconds, no faster than every 4 seconds. Back-to-back calls can blur a balance reading; the ledger's `measured_by` says which method was used. A row with `settled: false` was not measured. It does not mean the call was free.
4. **Keep a reserve.** A call that would leave fewer than `ELEVEN_RESERVE` credits (default 1000) is refused. Change it only when the user says so.

The cache and ledger live in `.elevenlabs/` in the folder the command runs from, so each project keeps its own record. `ELEVENLABS_HOME` moves it. `ledger.jsonl` is the record and is worth keeping in version control. `cache/` holds audio: tell the user to add `.elevenlabs/cache/` to `.gitignore`.

## The working order: cheap first

Never buy something you could have heard for free first.

1. **Choose the voice by ear, for free.** `voices --library --q "..." --lang en --previews <dir>`, then listen. Never generate a test sentence to choose a voice.
2. **Fit the script on paper.** Natural narration runs at about 2.6 words per second. If a line cannot fit its window, rewrite it before anything is spoken.
3. **Scratch take with flash** (`--model eleven_flash_v2_5`, half price) and `--timestamps`. It answers one question: does it fit? The timing comes back as data.
4. **Final take, one line at a time.** Use `eleven_multilingual_v2` with `--prev` and `--next` when the lines must sound like one read, or `eleven_v3` without stitching when its range is worth it. Check each take's pitch. Redo a line, never the whole script.
5. **Music: plan first.** Get a plan free from `plan`, or write one. Edit the sections until each one matches a scene, then render once with `music_v1`.
6. **Sound effects: one prompt, one take.** Describe what the moment means, and ask for the exact duration. Setting it is also far cheaper: about 29 credits for 2.6 seconds, against about 200 when the model chooses. Make a second take only after listening to the first.

## Rules

- **Cache first.** Check whether the request was already made before changing a word.
- **`--dry` before any batch,** and show the user the total estimate.
- **`--max N` on anything over 300 credits.**
- **Tag every call** with `--tag` and `--why`. A ledger row with no reason cannot be learned from.
- **Ask before a large spend.** Anything over about 2,000 credits, or 10% of what is left, needs the user's yes first.
- **Disclosure.** Synthesized voice and generated music count as AI-generated material on most social platforms. Tell the user to use each platform's AI disclosure label when they publish it.

## Failure messages

Errors are rewritten for people. A missing key names the file it belongs in. A missing permission names the exact row to switch on, and says the key does not need replacing. An invalid request says nothing was charged. Keep that habit for anything added here.

## Updates

This skill is versioned. Its version is `metadata.version` in the header of this file. `CHANGELOG.md` in this folder lists what changed in each version, newest first.

To check for a newer version, open the address on the `Latest:` line of `CHANGELOG.md` and compare its top version with the installed one. If the newer one is ahead, read every entry between the two and tell the user what changed before anything is updated. A `Breaking` section means the user has to do something. To update, reinstall the skill from its source repository, the same way it was installed.
