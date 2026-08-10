<div align="center">

# 🧰 itqan-skills

**Portable [Agent Skills](https://agentskills.io) — one directory, eight agents.**

[![Spec](https://img.shields.io/badge/Agent_Skills-conformant-5A67D8)](https://agentskills.io/specification)
[![Agents](https://img.shields.io/badge/agents-8-2F855A)](docs/COMPATIBILITY.md)
[![License](https://img.shields.io/badge/license-MIT-4A5568)](LICENSE)

</div>

---

## 📦 Skills

| Skill | Does | Needs |
| :-- | :-- | :-- |
| [`watch-video`](skills/watch-video) | Turns a video URL or local file into a transcript + frames the agent can read, so it can actually *watch* it | `ffmpeg`, `yt-dlp` |

---

## 🚀 Install

**Claude Code**

```
/plugin marketplace add itqanlab/skills
/plugin install watch-video@itqan-skills
```

**Everything else** — writes to `~/.agents/skills/`, the vendor-neutral path

```bash
git clone https://github.com/itqanlab/skills && cd skills
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

Seven read the neutral path. Claude Code is the sole exception and gets the marketplace, which is better there anyway — versioned, updatable, and able to bundle agents, hooks and MCP servers.

Verified paths, precedence and sources → [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md)

---

## 🗂 Layout

The skill directory **is** the Claude plugin directory. One copy, no build step, no per-agent variants.

```
skills/<name>/
├── SKILL.md            # portable to all 8 agents
├── scripts/            # referenced by relative path
├── README.md
└── .claude-plugin/     # Claude only; stripped on neutral installs
```

```
.claude-plugin/marketplace.json   Claude marketplace catalog
mcp/                              MCP servers, npm workspaces
scripts/                          install · validate
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

[CONTRIBUTING.md](CONTRIBUTING.md) — commit format, hooks, the bar for a new skill.

```
✨ feat(watch-video): add --lang flag for non-English captions
```

---

<div align="center">
<sub>MIT · <a href="https://github.com/itqanlab">Itqan Lab</a></sub>
</div>
