#!/usr/bin/env bash
# install.sh — install these skills for any Agent Skills compatible agent (macOS / Linux).
# Windows: use scripts/install.ps1 instead.
#
# Default target is ~/.agents/skills — the vendor-neutral path read by Codex, OpenCode,
# Cursor, Gemini CLI, GitHub Copilot, Amp and Goose. Claude Code is the one agent that
# does NOT read it; see --claude below and docs/COMPATIBILITY.md.
#
# Copies by default, because a copy behaves identically on every OS and every agent.
# Use --link for a live development loop.
#
# Usage: scripts/install.sh [skill...] [options]
#   (no skill names)   install every skill in this repo
#
#   --project          install into ./.agents/skills (ship skills with a repository)
#   --claude           also install into ~/.claude/skills (keeps .claude-plugin/)
#   --all              install to the neutral path AND every detected agent's own path
#   --target DIR       install into an explicit directory instead
#
#   --link             symlink instead of copy — edits go live immediately
#   --force            replace an existing entry, backing it up to
#                      <skills-dir>-backups/<name>.bak-<ts> (outside the skills
#                      directory, so agents do not load the backup as a skill)
#   --dry-run          print what would happen, change nothing
#   --detect           just report which agents are installed, then exit
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NEUTRAL="${HOME}/.agents/skills"

MODE="copy"; DRY=0; FORCE=0; DETECT_ONLY=0
WANT_PROJECT=0; WANT_CLAUDE=0; WANT_ALL=0
EXPLICIT_TARGET=""
WANTED=()

while [ $# -gt 0 ]; do
  case "$1" in
    --project) WANT_PROJECT=1; shift;;
    --claude)  WANT_CLAUDE=1; shift;;
    --all)     WANT_ALL=1; shift;;
    --target)  EXPLICIT_TARGET="$2"; shift 2;;
    --link)    MODE="link"; shift;;
    --copy)    MODE="copy"; shift;;
    --force)   FORCE=1; shift;;
    --dry-run) DRY=1; shift;;
    --detect)  DETECT_ONLY=1; shift;;
    -h|--help) sed -n '2,25p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0;;
    -*) echo "unknown option: $1" >&2; exit 2;;
    *) WANTED+=("$1"); shift;;
  esac
done

# ---------------------------------------------------------------- agent detection
# Each row: label | probe command | probe dir | own user-level skills dir ("-" if the
# agent only reads the neutral path)
AGENTS=(
  "Claude Code|claude|${HOME}/.claude|${HOME}/.claude/skills"
  "Codex|codex|${HOME}/.codex|-"
  "OpenCode|opencode|${HOME}/.config/opencode|${HOME}/.config/opencode/skills"
  "Cursor|cursor|${HOME}/.cursor|${HOME}/.cursor/skills"
  "Gemini CLI|gemini|${HOME}/.gemini|${HOME}/.gemini/skills"
  "GitHub Copilot|copilot|${HOME}/.copilot|${HOME}/.copilot/skills"
  "Amp|amp|${HOME}/.config/amp|${HOME}/.config/amp/skills"
  "Goose|goose|${HOME}/.config/goose|${HOME}/.config/goose/skills"
)

detected_labels=(); detected_dirs=()
detect_agents() {
  local row label probe dir own
  for row in "${AGENTS[@]}"; do
    IFS='|' read -r label probe dir own <<< "$row"
    if command -v "$probe" >/dev/null 2>&1 || [ -d "$dir" ]; then
      detected_labels+=("$label")
      detected_dirs+=("$own")
    fi
  done
}
detect_agents

if [ "$DETECT_ONLY" -eq 1 ]; then
  echo "Detected agents on this machine:"
  if [ ${#detected_labels[@]} -eq 0 ]; then
    echo "  (none found)"
  else
    for i in "${!detected_labels[@]}"; do
      if [ "${detected_dirs[$i]}" = "-" ]; then
        printf '  %-16s reads %s\n' "${detected_labels[$i]}" "$NEUTRAL"
      elif [ "${detected_labels[$i]}" = "Claude Code" ]; then
        printf '  %-16s does NOT read the neutral path — use the marketplace or --claude\n' "${detected_labels[$i]}"
      else
        printf '  %-16s reads %s (and %s)\n' "${detected_labels[$i]}" "$NEUTRAL" "${detected_dirs[$i]}"
      fi
    done
  fi
  exit 0
fi

# ---------------------------------------------------------------- resolve targets
TARGETS=()
if [ -n "$EXPLICIT_TARGET" ]; then
  TARGETS+=("$EXPLICIT_TARGET")
elif [ "$WANT_PROJECT" -eq 1 ]; then
  TARGETS+=("$(pwd)/.agents/skills")
else
  TARGETS+=("$NEUTRAL")
  [ "$WANT_CLAUDE" -eq 1 ] && TARGETS+=("${HOME}/.claude/skills")
  if [ "$WANT_ALL" -eq 1 ]; then
    for d in "${detected_dirs[@]}"; do
      [ "$d" = "-" ] && continue
      case " ${TARGETS[*]} " in *" $d "*) ;; *) TARGETS+=("$d");; esac
    done
  fi
fi

TS="$(date +%Y%m%d-%H%M%S)"
installed=0; skipped=0

want() {
  [ ${#WANTED[@]} -eq 0 ] && return 0
  local n="$1" w
  for w in "${WANTED[@]}"; do [ "$w" = "$n" ] && return 0; done
  return 1
}

# Claude Code loads a skill folder containing .claude-plugin/ as a full plugin, so keep
# it there. Every other agent ignores the directory, so strip it to stay clean.
keeps_plugin_dir() { case "$1" in *"/.claude/skills") return 0;; *) return 1;; esac; }

shopt -s nullglob
for target in "${TARGETS[@]}"; do
  echo "→ $target"
  [ "$DRY" -eq 1 ] || mkdir -p "$target"

  for skill_dir in "$REPO_ROOT"/skills/*/; do
    [ -f "${skill_dir}SKILL.md" ] || continue
    name="$(basename "$skill_dir")"
    want "$name" || continue
    src="${skill_dir%/}"
    dst="${target}/${name}"

    if [ -e "$dst" ] || [ -L "$dst" ]; then
      if [ "$MODE" = "link" ] && [ -L "$dst" ] && [ "$(readlink "$dst")" = "$src" ]; then
        echo "    ok       $name (already linked)"
        installed=$((installed+1)); continue
      fi
      if [ "$FORCE" -eq 1 ]; then
        # The backup must land OUTSIDE the skills directory. Agents discover any
        # directory in there, so a backup left alongside gets loaded as a second,
        # near-identical skill — which is worse than no backup at all.
        backup_dir="${target%/}-backups"
        echo "    replace  $name (backup -> ${backup_dir}/${name}.bak-${TS})"
        if [ "$DRY" -eq 0 ]; then
          mkdir -p "$backup_dir"
          mv "$dst" "${backup_dir}/${name}.bak-${TS}"
        fi
      else
        echo "    SKIP     $name — exists (re-run with --force to replace)"
        skipped=$((skipped+1)); continue
      fi
    fi

    if [ "$MODE" = "link" ]; then
      echo "    link     $name"
      [ "$DRY" -eq 1 ] || ln -s "$src" "$dst"
    else
      echo "    copy     $name"
      if [ "$DRY" -eq 0 ]; then
        mkdir -p "$dst"
        if keeps_plugin_dir "$target"; then
          (cd "$src" && tar -cf - .) | (cd "$dst" && tar -xf -)
        else
          (cd "$src" && tar --exclude='./.claude-plugin' -cf - .) | (cd "$dst" && tar -xf -)
        fi
      fi
    fi
    installed=$((installed+1))
  done
done

# ---------------------------------------------------------------- coverage report
echo
echo "installed: $installed   skipped: $skipped   mode: $MODE"
[ "$DRY" -eq 1 ] && echo "(dry run — nothing changed)"
echo

covered_neutral=0
for t in "${TARGETS[@]}"; do [ "$t" = "$NEUTRAL" ] && covered_neutral=1; done

if [ ${#detected_labels[@]} -gt 0 ]; then
  echo "Coverage for agents detected on this machine:"
  for i in "${!detected_labels[@]}"; do
    label="${detected_labels[$i]}"; own="${detected_dirs[$i]}"
    ok=1
    if [ "$label" = "Claude Code" ]; then
      ok=0
      for t in "${TARGETS[@]}"; do [ "$t" = "${HOME}/.claude/skills" ] && ok=1; done
    elif [ "$covered_neutral" -eq 0 ]; then
      ok=0
      for t in "${TARGETS[@]}"; do [ "$t" = "$own" ] && ok=1; done
    fi
    if [ "$ok" -eq 1 ]; then
      printf '  ✔ %s\n' "$label"
    else
      printf '  ✘ %s — not covered by this install\n' "$label"
    fi
  done
  echo
fi

if [ "$WANT_CLAUDE" -eq 0 ] && [ "$WANT_PROJECT" -eq 0 ] && [ -z "$EXPLICIT_TARGET" ]; then
  echo "Claude Code does not read $NEUTRAL. Its native channel is better anyway:"
  echo "  /plugin marketplace add itqanlab/agent-toolkit"
  echo "Or copy into ~/.claude/skills with: $0 --claude"
fi
exit 0
