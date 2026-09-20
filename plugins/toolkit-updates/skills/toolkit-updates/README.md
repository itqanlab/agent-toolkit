# toolkit-updates

Tells you which of your toolkit skills have a newer version, and exactly what changed in each one, before anything is updated.

## Just ask

You do not need to run anything. Once the skill is installed, say what you want in your own words:

> *"are my toolkit skills up to date?"*
> *"what changed in watch-video?"*
> *"is there anything new in the toolkit?"*
> *"update my skills"*

The agent checks, tells you in plain words what is new, and puts anything that needs your action first. It does not update anything until you say yes.

## Example

```
Toolkit updates (feed updated 2026-09-20)

cloudflare-ops  1.1.0  up to date

watch-video  1.0.0 -> 1.2.0  UPDATE AVAILABLE
  installed at ~/.agents/skills/watch-video
  What changed:
    1.1.0  2026-08-11
      Added: A setup wizard that checks for ffmpeg and yt-dlp and installs them.
      Fixed: Playlists and audio-only sources are handled.
    1.2.0  2026-09-20
      Added: This changelog, so you can see what changed in each version.
  To update: In a clone of https://github.com/itqanlab/agent-toolkit: git pull, then: ./scripts/install.sh --force watch-video

2 copies found (2 skills), 1 can be updated.
```

## How it works

1. It looks in the folders agents keep skills in, in your current project, and in the plugin folders of Claude Code and Codex. A symlinked install counts once.
2. It keeps only skills whose header says they come from this publisher. A skill with the same name from someone else is ignored.
3. It reads the version each copy declares, then reads the public update feed.
4. For every copy that is behind, it lists each release in between, oldest first. A breaking release is marked, and its `Breaking` lines come first.
5. It prints the update command that fits how that copy was installed. A Claude Code plugin gets the marketplace command, a Codex plugin gets the Codex one, and a linked copy only needs a `git pull`.

It never writes, installs or deletes anything.

## Options

| Option | Effect |
| :-- | :-- |
| `--available` | Also list toolkit skills that are not installed |
| `--json` | Structured output instead of text |
| `--feed ADDRESS_OR_FILE` | Read another feed. Also set by `AGENT_TOOLKIT_FEED` |
| `--dir FOLDER` | Also look in this folder of skills. Repeat it for more |

Exit codes: `0` everything is current, `10` an update is available, `2` the feed could not be read, `1` bad usage. That makes it easy to use in a script or a scheduled job.

## Requirements

**Node 18 or newer.** If you do not have it, the skill installs it for you. The agent runs this, or you can:

```bash
sh scripts/setup-deps.sh --check    # is everything present?
sh scripts/setup-deps.sh            # show the install command, ask, then run it
```

```powershell
.\scripts\setup-deps.ps1            # Windows
```

It needs network access to read the feed.

**In Codex**, the network is off by default, so the check fails with a message that says so. Allow it in `~/.codex/config.toml` and run it again. `scripts/install.sh` prints the exact lines. This skill writes nothing, so it does not need the credential folder.

## Limits

- It only sees skills from this publisher, in the usual folders. Anything else needs `--dir`.
- It reports and advises. It does not update by itself, on purpose.
- If the feed is down, it says so and stops. It does not guess a version.
- A copy whose header has no version shows as `0.0.0`, so it always looks behind.
- Plugin caches can keep old versions on disk. It treats the newest cached version as the installed one. It does not read the agent's own record of which version is enabled.

## Install

```bash
./scripts/install.sh toolkit-updates          # any agent
```

```
/plugin install toolkit-updates@itqan         # Claude Code
codex plugin add toolkit-updates@itqan       # Codex, after: codex plugin marketplace add itqanlab/agent-toolkit
```
