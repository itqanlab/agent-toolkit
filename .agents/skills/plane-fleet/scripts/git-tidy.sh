#!/usr/bin/env bash
# git-tidy.sh — keep the main checkout current and free of dead local branches.
#
# Run from the repo root. The PM runs it after every group reaches Done (team-pm §6),
# and anyone can run it by hand. Default is a DRY RUN; pass --apply to change anything.
#
#   1. fetch --prune
#   2. fast-forward the trunk and main (never rewrites, never touches a dirty tree)
#   3. delete a local branch ONLY when every commit on it is already in the trunk by
#      CONTENT (git cherry), which catches PRs that were rebased or squashed on GitHub,
#      where plain `git branch -d` refuses
#   4. report, never delete: branches with work not in the trunk, and stashes
#
# Why: 2026-10-02 the checkout had 96 local branches (33 with deleted remotes, 15 never
# pushed) and 3 stashes up to 4 months old. All of it had already landed. Nobody tidied
# after merging, and plain `git branch -d` refused every rebased PR branch.
set -euo pipefail

APPLY=0; [ "${1:-}" = "--apply" ] && APPLY=1
TRUNK=$(python3 -c "import json;print(json.load(open('.plane/config.json'))['git']['trunk'])" 2>/dev/null || echo develop)
run() { if [ $APPLY = 1 ]; then "$@"; else echo "  would run: $*"; fi; }

git fetch -q --prune origin
CUR=$(git branch --show-current)

echo "== fast-forward"
for b in "$TRUNK" main; do
  git show-ref -q "refs/heads/$b" || continue
  behind=$(git rev-list --count "$b..origin/$b"); ahead=$(git rev-list --count "origin/$b..$b")
  if [ "$ahead" != 0 ]; then echo "  $b: $ahead local commit(s) not on origin, left alone"; continue; fi
  [ "$behind" = 0 ] && { echo "  $b: up to date"; continue; }
  if [ "$b" = "$CUR" ]; then
    if [ -n "$(git status --porcelain --untracked-files=no)" ]; then echo "  $b: $behind behind, but the tree is dirty, left alone"; continue; fi
    run git merge -q --ff-only "origin/$b"
  else
    run git fetch -q origin "$b:$b"
  fi
  echo "  $b: $behind commit(s) behind -> fast-forwarded"
done

echo "== local branches"
deleted=0; kept=()
WT_BRANCHES=$(git worktree list --porcelain | awk '/^branch /{sub("refs/heads/","",$2);print $2}')
for b in $(git for-each-ref --format='%(refname:short)' refs/heads); do
  [ "$b" = "$TRUNK" ] || [ "$b" = main ] || [ "$b" = "$CUR" ] && continue
  echo "$WT_BRANCHES" | grep -qx "$b" && { kept+=("$b (checked out in a worktree)"); continue; }
  # a branch whose remote still exists and is ahead of the trunk is live work: skip it
  if git show-ref -q "refs/remotes/origin/$b" && [ "$(git cherry "origin/$TRUNK" "origin/$b" | grep -c '^+')" != 0 ]; then
    continue
  fi
  if [ "$(git cherry "origin/$TRUNK" "$b" | grep -c '^+')" = 0 ]; then
    run git branch -D "$b" >/dev/null; deleted=$((deleted+1))
  else
    kept+=("$b ($(git cherry "origin/$TRUNK" "$b" | grep -c '^+') commit(s) not in $TRUNK, last $(git log -1 --format=%ad --date=short "$b"))")
  fi
done
echo "  $( [ $APPLY = 1 ] && echo deleted || echo would delete ) $deleted branch(es) fully contained in $TRUNK"
for k in "${kept[@]:-}"; do [ -n "$k" ] && echo "  KEEP: $k"; done

echo "== stashes (never dropped by this script, read them and decide)"
git stash list --format='  %gd  %cr  %gs' || true
