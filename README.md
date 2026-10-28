<div align="center">

# 🧰 Itqan Agent Toolkit

**Portable tooling for AI coding agents.**
Skills · MCP servers · Plugins — one repo, eight agents.

**[agent-toolkit.itqanlab.com](https://agent-toolkit.itqanlab.com)**

[![Spec](https://img.shields.io/badge/Agent_Skills-conformant-5A67D8)](https://agentskills.io/specification)
[![Agents](https://img.shields.io/badge/agents-8-2F855A)](docs/COMPATIBILITY.md)
[![License](https://img.shields.io/badge/license-MIT-4A5568)](LICENSE)

</div>

---

## 📦 What's inside

| | Component | Portable to | Lives in |
| :-: | :-- | :-- | :-- |
| 🧠 | **Skills** | All 8 agents | [`plugins/*/skills/`](plugins) |
| 🧩 | **Plugins**, the packaging every item ships in. Later also bundles, subagents, hooks | Claude Code, Codex | [`plugins/`](plugins) |
| 🔌 | **MCP servers** | Any MCP client | [`mcp/`](mcp) |

Skills are the flagship: written to the open standard, they work everywhere unchanged. Every skill also ships as a plugin, so Claude Code and Codex can install and update it natively. Subagents and hooks have no cross-agent equivalent, so they stay Claude Code only.

---

## 🧠 Skills

<!-- skills:start -->
| Skill | Category | Version | Does | Needs |
| :-- | :-- | :-- | :-- | :-- |
| [`cloudflare-ops`](plugins/cloudflare-ops/skills/cloudflare-ops) | devops | [2.1.1](plugins/cloudflare-ops/skills/cloudflare-ops/CHANGELOG.md) | Connect a Cloudflare account in two minutes, then manage DNS, subdomains, Pages and R2 from the agent. | `node` |
| [`dokploy-ops`](plugins/dokploy-ops/skills/dokploy-ops) | devops | [2.1.1](plugins/dokploy-ops/skills/dokploy-ops/CHANGELOG.md) | Connect one or more self-hosted Dokploy installations, then run what is deployed on them from the agent — deploy and watch the build to the end, read logs, restart, check domains and health. | `node` |
| [`hetzner-ops`](plugins/hetzner-ops/skills/hetzner-ops) | devops | [2.1.1](plugins/hetzner-ops/skills/hetzner-ops/CHANGELOG.md) | Connect one or more Hetzner Cloud projects, then run the servers from the agent — create, resize, reboot, delete, SSH keys, firewalls, DNS and running costs. | `node` |
| [`namecheap-ops`](plugins/namecheap-ops/skills/namecheap-ops) | devops | [2.1.1](plugins/namecheap-ops/skills/namecheap-ops/CHANGELOG.md) | Connect one or more Namecheap accounts, then run the domains from the agent — expiry and auto-renew, nameservers, availability, prices and DNS records. | `node` |
| [`plane-fleet`](plugins/plane-fleet/skills/plane-fleet) | devops | [2.3.0](plugins/plane-fleet/skills/plane-fleet/CHANGELOG.md) | Run work from a Plane board with teams of agent roles, one section per kind of work. | `git`, `node` |
| [`audio-narrate`](plugins/audio-narrate/skills/audio-narrate) | media | [1.0.0](plugins/audio-narrate/skills/audio-narrate/CHANGELOG.md) | Turn text into natural English or Arabic narration for free: one file, or one file per scene for a video. | `python`, `uv`, `ffmpeg` |
| [`audio-transcribe`](plugins/audio-transcribe/skills/audio-transcribe) | media | [1.0.0](plugins/audio-transcribe/skills/audio-transcribe/CHANGELOG.md) | Turn speech in any audio or video into text, on this machine, free. | `ffmpeg`, `yt-dlp` |
| [`elevenlabs-studio`](plugins/elevenlabs-studio/skills/elevenlabs-studio) | media | [1.2.0](plugins/elevenlabs-studio/skills/elevenlabs-studio/CHANGELOG.md) | Voice-over, sound effects, music, transcription, voice changing, noise removal and dubbing with ElevenLabs, from the agent, spending the credits on purpose. | `node` |
| [`higgsfield-studio`](plugins/higgsfield-studio/skills/higgsfield-studio) | media | [1.1.0](plugins/higgsfield-studio/skills/higgsfield-studio/CHANGELOG.md) | Make images, video, audio, 3D, ads, product shoots, thumbnails, explainers and websites with Higgsfield from the agent, and spend the credits on purpose. Also: [`brandkit`](plugins/higgsfield-studio/skills/higgsfield-studio-brandkit), [`marketplace-cards`](plugins/higgsfield-studio/skills/higgsfield-studio-marketplace-cards), [`product-photoshoot`](plugins/higgsfield-studio/skills/higgsfield-studio-product-photoshoot), [`soul-id`](plugins/higgsfield-studio/skills/higgsfield-studio-soul-id), [`video-explainer`](plugins/higgsfield-studio/skills/higgsfield-studio-video-explainer), [`websites`](plugins/higgsfield-studio/skills/higgsfield-studio-websites), [`youtube-thumbnail`](plugins/higgsfield-studio/skills/higgsfield-studio-youtube-thumbnail). | `node` |
| [`image-prompt`](plugins/image-prompt/skills/image-prompt) | media | [1.0.1](plugins/image-prompt/skills/image-prompt/CHANGELOG.md) | Write image prompts in the project's brand, sized for each platform, ready for any image generator. | `node` |
| [`video-prompt`](plugins/video-prompt/skills/video-prompt) | media | [1.0.1](plugins/video-prompt/skills/video-prompt/CHANGELOG.md) | Write video prompts in the project's brand, sized and timed for each platform, ready for any video generator. | `node` |
| [`video-watch`](plugins/video-watch/skills/video-watch) | media | [3.0.0](plugins/video-watch/skills/video-watch/CHANGELOG.md) | Let the agent watch a video — any of 1750+ sites or a local file. | `ffmpeg`, `yt-dlp` |
| [`toolkit-credentials`](plugins/toolkit-credentials/skills/toolkit-credentials) | productivity | [2.1.1](plugins/toolkit-credentials/skills/toolkit-credentials/CHANGELOG.md) | Shared credential setup and storage for skills that need an API key or token. | `node` |
| [`toolkit-updates`](plugins/toolkit-updates/skills/toolkit-updates) | productivity | [2.2.0](plugins/toolkit-updates/skills/toolkit-updates/CHANGELOG.md) | Check whether the toolkit skills installed on this machine are up to date, and see exactly what changed in each newer version before updating. | `node` |
<!-- skills:end -->

---

## 🚀 Install

**Claude Code**

```
/plugin marketplace add itqanlab/agent-toolkit
/plugin install watch-video@itqan
```

**Codex**

```
codex plugin marketplace add itqanlab/agent-toolkit
codex plugin add watch-video@itqan
```

**Everything else** — writes to `~/.agents/skills/`, the vendor-neutral path

```bash
git clone https://github.com/itqanlab/agent-toolkit && cd agent-toolkit
./scripts/install.sh              # macOS · Linux
.\scripts\install.ps1             # Windows
```

| Flag | Effect |
| :-- | :-- |
| `--detect` | List agents found on this machine |
| `--claude` | Also install to `~/.claude/skills/` |
| `--project` | Install to `./.agents/skills/`, to ship with a repo |
| `--link` | Symlink instead of copy — edits go live (Windows: junction) |
| `--dry-run` `--force` | Preview · replace existing |

Prints per-agent coverage when it finishes.

**Codex** runs commands in a sandbox with no network by default. The installer prints the settings that let skills call a web API and save a credential. Details and test results: [Codex](docs/COMPATIBILITY.md#codex).

**Gemini CLI, Copilot CLI and Amp** have their own install commands too, and they work with this repository. Amp adds one skill at a time, by path. See [COMPATIBILITY](docs/COMPATIBILITY.md#tested-on-the-real-tools).

**Stay current.** Every skill keeps a `CHANGELOG.md`. All releases are listed at [/updates](https://agent-toolkit.itqanlab.com/updates/), and as JSON at [/updates.json](https://agent-toolkit.itqanlab.com/updates.json). An agent can compare what is installed with that list and tell you exactly what changed before it updates.

---

## 🤖 Agents

| | Agent | Channel |
| :-: | :-- | :-- |
| 🟣 | **Claude Code** | Plugin marketplace |
| ⚫ | **Codex** | `~/.agents/skills/` |
| 🟠 | **OpenCode** | `~/.agents/skills/` |
| 🔵 | **Cursor** | `~/.agents/skills/` |
| 🔷 | **Gemini CLI** | `~/.agents/skills/` |
| 🐙 | **Copilot / VS Code** | `~/.agents/skills/` |
| 🟡 | **Amp** | `~/.agents/skills/` |
| 🦆 | **Goose** | `~/.agents/skills/` |

Seven read the neutral path. Claude Code is the sole exception and gets the marketplace, which is better there anyway — versioned, updatable, and able to bundle subagents, hooks and MCP servers.

Verified paths, precedence and sources → [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md)

---

## 🗂 Layout

One source, no copies. Every item is a plugin folder, and the skill sits inside it in the shape Codex requires and every other agent already reads.

```
plugins/<name>/
├── .claude-plugin/plugin.json    # Claude Code manifest, written by hand
├── .codex-plugin/plugin.json     # Codex manifest, generated
└── skills/<name>/                # the skill, portable to all 8 agents
    ├── SKILL.md
    ├── README.md
    ├── CHANGELOG.md
    └── scripts/                  # referenced by relative path
```

```
plugins/                          every item: a plugin folder holding its skill
mcp/                              MCP servers, npm workspaces
catalog/                          the list of categories
.claude-plugin/marketplace.json   Claude Code catalog, generated. Id: itqan
.agents/plugins/marketplace.json  Codex catalog, generated
.agents/skills/                    a copy of every skill folder for Amp, generated. Edit plugins/, not this
scripts/                          install · validate · build-catalog
site/                             generated site → agent-toolkit.itqanlab.com
docs/                             COMPATIBILITY · AUTHORING · PUBLISHING
```

Other agents install just the skill folder. It carries its own README and CHANGELOG.

---

## 🔍 Validate

```bash
./scripts/validate.sh
```

Checks spec `name`/`description` rules, name↔directory match, referenced scripts exist and are executable, that the generated catalogs and manifests match the source, and that no vendor variable or absolute path leaked into a `SKILL.md`. Runs the upstream reference validator from the spec authors when `uv` is present, and Codex's own plugin validator when Codex is installed. Wired into `pre-commit`, and run again in CI.

---

## 🤝 Contributing

[CONTRIBUTING.md](CONTRIBUTING.md) — commit format, hooks, the bar for a new component.

```
✨ feat(watch-video): add --lang flag for non-English captions
```

---

<div align="center">
<sub>MIT · <a href="https://github.com/itqanlab">Itqan Lab</a></sub>
</div>
