#!/usr/bin/env bash
# board-drift.sh — cross-check open tickets against merged work on the trunk.
#
# The board is only a source of truth if it matches reality. Reality lives in
# git. This reports where the two disagree so a human decides; it never changes
# anything itself.
#
# Usage:
#   printf '%s\n' 12 34 56 | board-drift.sh <IDENTIFIER> [trunk]
#   board-drift.sh PROJ develop < open-ticket-numbers.txt
#
# stdin  : ticket NUMBERS (one per line) the board currently lists as open
#          (Todo / In Progress) — the caller gets these from the plane MCP (workitem list).
# stdout : one block per drifted ticket, then a summary.
#
# Exit: 0 = no drift, 1 = drift found, 2 = bad usage / unproven check.
#
# ── What a hit means, and what it does not ───────────────────────────────────
# A hit means a commit whose SUBJECT names the ticket reached the trunk. It does
# NOT mean the ticket is finished — partial work, follow-ups and reverts all
# carry the same id. Every hit is a CANDIDATE to close that a human confirms
# against the acceptance criteria. The job is to shrink the pile you check by
# hand, not to decide for you.
#
# ── Two matching traps this script exists to avoid ───────────────────────────
# 1. `git log --grep=X` searches the whole commit MESSAGE, body included. A
#    ticket cited in passing ("regression introduced by PROJ-91") then looks
#    implemented. Real case: that inflated one audit by ~30%. So match the
#    SUBJECT only, via `--format='%h %s'` piped to grep.
# 2. `\b` is unsupported by git's and BSD grep's ERE and matches NOTHING —
#    silently. A word-boundary bug makes a drifted board report clean, which is
#    worse than no check at all. Use `([^0-9]|$)`, and keep the self-test below
#    so that failure can never be silent again.

set -euo pipefail

IDENTIFIER="${1:-}"
TRUNK="${2:-develop}"

[[ -n "$IDENTIFIER" ]] || { echo "usage: board-drift.sh <IDENTIFIER> [trunk] < ticket-numbers" >&2; exit 2; }
git rev-parse --git-dir >/dev/null 2>&1 || { echo "not a git repository" >&2; exit 2; }

OPEN_IDS="$(sort -un)"
[[ -n "$OPEN_IDS" ]] || { echo "no ticket numbers on stdin" >&2; exit 2; }

REF="origin/$TRUNK"
git rev-parse --verify --quiet "$REF" >/dev/null || REF="$TRUNK"
git rev-parse --verify --quiet "$REF" >/dev/null || {
  echo "cannot resolve trunk '$TRUNK' (tried origin/$TRUNK and $TRUNK)" >&2; exit 2; }

git fetch origin "$TRUNK" --quiet 2>/dev/null || true   # non-fatal when offline

SUBJECTS="$(git log --format='%h %s' "$REF")"

# ── Self-test: prove the matcher can actually match ──────────────────────────
probe="$(printf '%s\n' "$SUBJECTS" | grep -cE "${IDENTIFIER}-[0-9]+([^0-9]|$)" || true)"
if [[ "$probe" -eq 0 ]]; then
  echo "SELF-TEST FAILED: no commit subject on $REF references ${IDENTIFIER}-<n>." >&2
  echo "Either this repo does not put ticket ids in commit subjects, or the matcher" >&2
  echo "is broken. Refusing to report a clean board from an unproven check." >&2
  exit 2
fi

echo "Board drift — $IDENTIFIER against $REF"
date '+%Y-%m-%d %H:%M'
echo "matcher self-test: OK ($probe subjects carry a ticket id)"
echo

total=0
drift=0

while read -r n; do
  [[ -n "$n" ]] || continue
  total=$((total + 1))

  hits="$(printf '%s\n' "$SUBJECTS" | grep -E "${IDENTIFIER}-${n}([^0-9]|$)" || true)"
  [[ -n "$hits" ]] || continue

  drift=$((drift + 1))
  count="$(printf '%s\n' "$hits" | grep -c . || true)"
  echo "── ${IDENTIFIER}-${n} — OPEN on the board, ${count} merged commit(s) on ${TRUNK}"
  printf '%s\n' "$hits" | sed 's/^/     /'
  echo
done <<< "$OPEN_IDS"

echo "─────────────────────────────────────────────"
echo "open tickets checked : $total"
echo "with merged work     : $drift   ← confirm each, then close or explain"
echo "with none            : $((total - drift))   ← genuinely open"
echo
echo "A hit means work naming that ticket reached $TRUNK. It does NOT mean the"
echo "ticket is complete. Read the commits, check the acceptance criteria, and"
echo "close only what is actually done."

[[ "$drift" -eq 0 ]] || exit 1
