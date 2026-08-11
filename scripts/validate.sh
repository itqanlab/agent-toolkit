#!/usr/bin/env bash
# validate.sh — enforce the Agent Skills spec plus this repo's portability rules.
#
# Run before every push. Everything checked here is a rule that, if broken, makes a
# skill fail or misbehave on at least one of the agents listed in docs/COMPATIBILITY.md.
#
# Usage: scripts/validate.sh [skill...]
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WANTED=("$@")
errors=0; warnings=0; checked=0

err()  { printf '  ✘ %s\n' "$1"; errors=$((errors+1)); }
warn() { printf '  ! %s\n' "$1"; warnings=$((warnings+1)); }

want() {
  [ ${#WANTED[@]} -eq 0 ] && return 0
  local n="$1" w
  for w in "${WANTED[@]}"; do [ "$w" = "$n" ] && return 0; done
  return 1
}

# Extract a top-level scalar from the YAML frontmatter block.
fm_field() {
  awk -v key="$1" '
    NR==1 && $0=="---" { inside=1; next }
    inside && $0=="---" { exit }
    inside && index($0, key ":")==1 {
      sub("^" key ": *", ""); gsub(/^"|"$/, ""); print; exit
    }
  ' "$2"
}

shopt -s nullglob
for skill_dir in "$REPO_ROOT"/skills/*/; do
  name="$(basename "$skill_dir")"
  want "$name" || continue
  checked=$((checked+1))
  echo "$name"

  skill_md="${skill_dir}SKILL.md"
  if [ ! -f "$skill_md" ]; then
    err "no SKILL.md — a skill directory must contain one"
    continue
  fi

  # --- frontmatter presence
  if [ "$(head -1 "$skill_md")" != "---" ]; then
    err "SKILL.md must begin with a YAML frontmatter block (---)"
    continue
  fi

  fm_name="$(fm_field name "$skill_md")"
  fm_desc="$(fm_field description "$skill_md")"

  # --- name rules (spec)
  if [ -z "$fm_name" ]; then
    err "frontmatter is missing the required 'name' field"
  else
    [ "$fm_name" = "$name" ] || err "frontmatter name '$fm_name' must match directory name '$name'"
    [ ${#fm_name} -le 64 ] || err "name is ${#fm_name} chars, max is 64"
    printf '%s' "$fm_name" | grep -qE '^[a-z0-9]+(-[a-z0-9]+)*$' \
      || err "name '$fm_name' must be lowercase alphanumerics and single hyphens, not starting or ending with a hyphen"
  fi

  # --- description rules (spec)
  if [ -z "$fm_desc" ]; then
    err "frontmatter is missing the required 'description' field"
  else
    [ ${#fm_desc} -le 1024 ] || err "description is ${#fm_desc} chars, max is 1024"
    [ ${#fm_desc} -ge 40 ] || warn "description is very short — it is the only thing an agent sees when deciding to invoke this skill"

    # The generated site leads each skill page with these phrases, so losing them
    # to a stray separator costs the skill its most useful section.
    case "$fm_desc" in
      *Trigger*)
        printf '%s' "$fm_desc" | grep -qE 'Triggers?:' \
          || warn "description mentions triggers but not in the form 'Triggers: '...', '...'' — the catalog and site parse that exact form"
        printf '%s' "$fm_desc" | grep -q "'" \
          || warn "description has a Triggers section with no single-quoted phrases in it — nothing will be extracted"
        ;;
      *) warn "description has no 'Triggers: ...' section — agents and the catalog use those phrases to match user requests";;
    esac
  fi

  # --- portability rules (this repo)
  if grep -qn 'CLAUDE_PLUGIN_ROOT\|CLAUDE_PROJECT_DIR\|CLAUDE_PLUGIN_DATA' "$skill_md"; then
    err "SKILL.md references a Claude-only variable; the spec requires paths relative to the skill root"
  fi
  if grep -qnE '(^|[^a-zA-Z0-9_])(/Users/|/home/[a-z]|~/\.claude|~/\.agents)' "$skill_md"; then
    err "SKILL.md contains an absolute or home-relative path; use paths relative to the skill root"
  fi
  if grep -qniE '\bclaude code\b|\bcursor\b|\bopencode\b|\bgemini cli\b|\bcopilot\b' "$skill_md"; then
    warn "SKILL.md names a specific agent; the body is read verbatim by all agents, so keep vendor references in README.md"
  fi

  # --- body size (progressive disclosure)
  lines=$(wc -l < "$skill_md" | tr -d ' ')
  [ "$lines" -le 500 ] || warn "SKILL.md is $lines lines; the spec recommends under 500, move detail into references/"

  # --- referenced scripts must exist and be executable
  while IFS= read -r ref; do
    [ -z "$ref" ] && continue
    if [ ! -f "${skill_dir}${ref}" ]; then
      err "SKILL.md references '$ref' which does not exist in the skill directory"
    elif [ ! -x "${skill_dir}${ref}" ] && case "$ref" in
           scripts/*.ps1) false;;   # PowerShell ignores the Unix executable bit
           scripts/*)     true;;
           *)             false;;   # references/ and assets/ are read, not run
         esac; then
      warn "'$ref' is not executable (chmod +x), which some agents require"
    fi
  done < <(grep -oE '(scripts|references|assets)/[A-Za-z0-9._/-]+' "$skill_md" | sort -u)

  # --- Claude packaging agreement, when present
  plugin_json="${skill_dir}.claude-plugin/plugin.json"
  if [ -f "$plugin_json" ]; then
    p_name=$(grep -oE '"name"[[:space:]]*:[[:space:]]*"[^"]*"' "$plugin_json" | head -1 | sed 's/.*"\([^"]*\)"$/\1/')
    [ "$p_name" = "$name" ] || err "plugin.json name '$p_name' must match directory name '$name'"

    p_ver=$(grep -oE '"version"[[:space:]]*:[[:space:]]*"[^"]*"' "$plugin_json" | head -1 | sed 's/.*"\([^"]*\)"$/\1/')
    m_ver=$(awk -v n="\"$name\"" '$0 ~ n {found=1} found && /"version"/ {gsub(/[^0-9.]/,""); print; exit}' "$REPO_ROOT/.claude-plugin/marketplace.json")
    if [ -n "$p_ver" ] && [ -n "$m_ver" ] && [ "$p_ver" != "$m_ver" ]; then
      err "version mismatch: plugin.json says $p_ver, marketplace.json says $m_ver"
    fi
    grep -q "\"source\"[[:space:]]*:[[:space:]]*\"\./skills/$name\"" "$REPO_ROOT/.claude-plugin/marketplace.json" \
      || warn "no marketplace.json entry with source ./skills/$name — Claude Code users will not see this skill"
  fi

  [ -f "${skill_dir}README.md" ] || warn "no README.md — this is what catalog reviewers read"
done

echo
if [ "$checked" -eq 0 ]; then
  echo "no skills matched"; exit 1
fi

# --- upstream conformance, via the reference validator from the spec authors.
# Python package, Apache-2.0, in the official agentskills/agentskills repo.
# (The unrelated `skills-ref` package on npm is not it — do not use that one.)
if command -v uvx >/dev/null 2>&1; then
  echo "skills-ref (upstream reference validator)"
  for skill_dir in "$REPO_ROOT"/skills/*/; do
    name="$(basename "$skill_dir")"
    want "$name" || continue
    out=$(uvx --quiet --from "git+https://github.com/agentskills/agentskills.git#subdirectory=skills-ref" \
          skills-ref validate "$skill_dir" 2>&1) \
      && printf '  ✔ %s\n' "$name" \
      || { printf '  ✘ %s\n%s\n' "$name" "$out" | sed 's/^/    /'; errors=$((errors+1)); }
  done
  echo
else
  echo "(skipped skills-ref — install uv to run the upstream reference validator)"
  echo
fi

echo "checked: $checked   errors: $errors   warnings: $warnings"
[ "$errors" -gt 0 ] && exit 1
exit 0
