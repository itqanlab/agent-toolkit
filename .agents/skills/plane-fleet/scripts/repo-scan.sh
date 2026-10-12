#!/usr/bin/env bash
# repo-scan.sh — the repo-side half of the pre-pick triage.
#
# The plane MCP's triage action answers the Plane-side questions (size, schema
# words, cited paths, vague scope, decision words and comments). It cannot see
# the repo. This script answers the rest, for one ticket, in one line:
#
#   trunk-commits:N <first subject>   commits on origin/<trunk> whose SUBJECT names the ticket
#   prs:#12:MERGED,#15:OPEN           PRs whose title or branch names the ticket exactly
#   missing-paths:a b                 cited paths that do not exist on origin/<trunk>
#
# Usage:
#   repo-scan.sh <IDENT> <trunk> [paths...]
#   repo-scan.sh PROJ-373 develop apps/client/src/app/foo.ts libs/server/x
#
# Pass the `paths` the triage action returned. Run it from inside the repo.
# It makes no Plane call. Every hit is a CANDIDATE for a look, never a verdict.
#
# Traps it shares with board-drift.sh:
# - Subject-only match. A ticket named only in a commit BODY is not counted, and
#   "PROJ-37" must not match "PROJ-373", so the id must end at a non-digit.
# - GitHub search is fuzzy ("PROJ-540" also hits titles with "540"), so the
#   gh results are filtered again for the exact id in title or branch.
# - Run `git fetch origin <trunk>` first if the clone may be stale.
#
# Exit: 0 = scan ran, 2 = bad usage.

set -uo pipefail

IDENT="${1:-}"; TRUNK="${2:-}"
[[ -n "$IDENT" && -n "$TRUNK" ]] || { echo "usage: repo-scan.sh <IDENT> <trunk> [paths...]" >&2; exit 2; }
shift 2
git rev-parse --git-dir >/dev/null 2>&1 || { echo "repo-scan.sh: not inside a git repo" >&2; exit 2; }
git rev-parse --verify -q "origin/$TRUNK" >/dev/null || { echo "repo-scan.sh: origin/$TRUNK not found" >&2; exit 2; }

PAT="${IDENT}([^0-9]|\$)"

commits=$(git log "origin/$TRUNK" --format='%h %s' -E --grep="$PAT" 2>/dev/null \
  | awk -v id="$IDENT" '{ s=$0; sub(/^[^ ]+ /, "", s); if (match(s, id "([^0-9]|$)")) print }')
ncommits=$(printf '%s' "$commits" | grep -c . || true)
first=$(printf '%s\n' "$commits" | head -1 | cut -c1-60)

prs="-"
if command -v gh >/dev/null 2>&1; then
  prs=$(gh pr list --state all --search "$IDENT" --limit 50 \
        --json number,state,title,headRefName \
        --jq ".[] | select((.title + \" \" + .headRefName) | test(\"${IDENT}([^0-9]|\$)\")) | \"#\\(.number):\\(.state)\"" \
        2>/dev/null | paste -sd, -)
  [[ -n "$prs" ]] || prs="-"
else
  prs="gh-missing"
fi

missing=()
for p in "$@"; do
  p="${p%.}"
  [[ -n "$p" ]] || continue
  git cat-file -t "origin/$TRUNK:$p" >/dev/null 2>&1 || missing+=("$p")
done

printf '%s\ttrunk-commits:%s%s\tprs:%s\tmissing-paths:%s\n' \
  "$IDENT" "$ncommits" "${first:+ $first}" "$prs" "${missing[*]:--}"
