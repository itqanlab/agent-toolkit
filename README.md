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
| 🧠 | **Skills** | All 8 agents | [`skills/`](skills) |
| 🔌 | **MCP servers** | Any MCP client | [`mcp/`](mcp) |
| 🧩 | **Plugins** — multi-skill bundles, subagents, hooks, commands | Claude Code | [`plugins/`](plugins) |

Skills are the flagship: written to the open standard, they work everywhere unchanged. Subagents and hooks have no cross-agent equivalent, so they ship as Claude Code plugins.

---

## 🧠 Skills

<!-- skills:start -->
| Skill | Category | Version | Does | Needs |
| :-- | :-- | :-- | :-- | :-- |
| [`cloudflare-ops`](skills/cloudflare-ops) | devops | [1.1.0](skills/cloudflare-ops/CHANGELOG.md) | Connect a Cloudflare account in two minutes, then manage DNS, subdomains, Pages and R2 from the agent. | `node` |
| [`dokploy-ops`](skills/dokploy-ops) | devops | [1.1.0](skills/dokploy-ops/CHANGELOG.md) | Connect one or more self-hosted Dokploy installations, then run what is deployed on them from the agent — deploy and watch the build to the end, read logs, restart, check domains and health. | `node` |
| [`hetzner-ops`](skills/hetzner-ops) | devops | [1.1.0](skills/hetzner-ops/CHANGELOG.md) | Connect one or more Hetzner Cloud projects, then run the servers from the agent — create, resize, reboot, delete, SSH keys, firewalls, DNS and running costs. | `node` |
| [`namecheap-ops`](skills/namecheap-ops) | devops | [1.1.0](skills/namecheap-ops/CHANGELOG.md) | Connect one or more Namecheap accounts, then run the domains from the agent — expiry and auto-renew, nameservers, availability, prices and DNS records. | `node` |
| [`watch-video`](skills/watch-video) | media | [1.2.0](skills/watch-video/CHANGELOG.md) | Let the agent watch a video — any of 1750+ sites or a local file. | `ffmpeg`, `yt-dlp` |
| [`toolkit-credentials`](skills/toolkit-credentials) | productivity | [1.1.0](skills/toolkit-credentials/CHANGELOG.md) | Shared credential setup and storage for skills that need an API key or token. | `node` |
<!-- skills:end -->

---

## 🚀 Install

**Claude Code**

```
/plugin marketplace add itqanlab/agent-toolkit
/plugin install watch-video@itqan
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

**Codex** runs commands in a sandbox with no network by default. The installer prints the two settings that let skills call a web API and save a credential. Details and test results: [Codex](docs/COMPATIBILITY.md#codex).

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

A single-skill directory **is** its own Claude plugin. One copy, no build step, no per-agent variants.

```
skills/<name>/
├── SKILL.md            # portable to all 8 agents
├── scripts/            # referenced by relative path
├── README.md
└── .claude-plugin/     # Claude only; stripped on neutral installs
```

```
skills/                           portable skills
plugins/                          multi-component Claude Code bundles
mcp/                              MCP servers, npm workspaces
.claude-plugin/marketplace.json   marketplace catalog — id: itqan
scripts/                          install · validate
site/                             generated site → agent-toolkit.itqanlab.com
docs/                             COMPATIBILITY · AUTHORING · PUBLISHING
```

---

## 🔍 Validate

```bash
./scripts/validate.sh
```

Checks spec `name`/`description` rules, name↔directory match, referenced scripts exist and are executable, version agreement between `plugin.json` and `marketplace.json`, and that no vendor variable or absolute path leaked into a `SKILL.md`. Runs the upstream reference validator from the spec authors when `uv` is present. Wired into `pre-commit`.

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
