# engineer · worktree

> Part of the engineer role (`engineering/engineer/role.md`). Read it when the gate is done and you set up your own checkout. Paths written as
> `core/…` and `engineering/…` are relative to the fleet folder, three levels above this file.

## 2) Worktree — your own isolated checkout

**You never work in the shared main checkout, and you never wait for it to be free.** This is
what makes you safe to run alongside sibling engineer sessions.

```bash
git fetch origin
git worktree add .claude/worktrees/<IDENTIFIER>-<n>-<slug> \
  -b <type>/<IDENTIFIER>-<n>-<slug> origin/<trunk>
cd .claude/worktrees/<IDENTIFIER>-<n>-<slug>
pnpm install --frozen-lockfile
```

**Branch off `origin/<trunk>` and nothing else**: not another PR's branch, and not your local
`HEAD`. Before your first commit, `git log --oneline origin/<trunk>..HEAD` must print nothing.
If it prints commits, you branched off the wrong base: delete the worktree and branch, and start
again. (2026-09-30: an engineer branched off an open PR's branch, and its PR carried someone
else's commits.) A rework engineer is the one exception: it continues on the existing PR branch.

**Give the worktree its own real `node_modules` — do not symlink it into the main checkout's.**
A symlinked `node_modules` causes two confirmed failure modes:

- Running the repo's real `nx sync:check` pre-push command against a symlinked `node_modules`
  fails with `[ERR_PNPM_ABORTED_REMOVE_MODULES_DIR_NO_TTY]` — a false failure even on a
  pristine, unmodified trunk checkout. Root cause: `nx sync:check`'s deps-status step shells out
  to `pnpm install` internally, and pnpm — seeing the symlinked `node_modules` doesn't match its
  lockfile-derived expected state — tries to purge/reinstall it, which it refuses to do
  non-interactively (no TTY). This is **not** an nx dependency-graph bug: a direct
  `nx graph --file=...` diff between a symlinked-node_modules worktree and the main checkout
  shows identical computed dependencies in both, so `nx reset` / `NX_ISOLATE_PLUGINS=false` are
  irrelevant — the failure is pnpm's own auto-repair aborting. (Root-caused on one ticket; an
  earlier version of this note wrongly attributed the failure to nx silently dropping
  cross-package deps — that claim did not reproduce under direct testing.)
- Any pnpm auto-repair triggered from inside the worktree (e.g. by prettier/nx commands adjusting
  the lockfile or store links) writes *through* the symlink into the shared directory, and can
  corrupt the **main checkout's** `node_modules` — including for other workers running there or
  in sibling worktrees. (Observed once.)

`pnpm install --frozen-lockfile` avoids both: it resolves entirely from pnpm's local
content-addressable store (shared across worktrees/checkouts on the same machine), so it's cheap
— typically 10–15s, no network fetch — and gives you an independent, real `node_modules` that
can't write back into anyone else's checkout.

**Run this install before any other tool touches `node_modules` in the worktree** — in
particular, never run `pnpm install`, prettier, or an nx command that could trigger a pnpm
auto-repair while `node_modules` is still a bare symlink to the main repo; that's exactly the
sequence that corrupts the shared directory.

Generating an ORM client inside your worktree is fine: it lands in your own `node_modules`.
If you find mid-implementation that you need a schema change you didn't anticipate at `engineering/engineer/skills/investigate.md` §1,
**stop, flag it the same way (`engineering/engineer/skills/investigate.md` §1.4), and let the PM decide** before authoring a
migration.

**First: is this ticket already half-built?** You may be a fresh session on a ticket a previous
worker died holding.

```bash
git worktree list                                           # a stale worktree for this ticket?
git branch -a --list '*<IDENTIFIER>-<n>*'                    # a branch already exists?
gh pr list --state all --search "<IDENTIFIER>-<n>"           # a PR already exists?
```

| What you find | Do |
|---|---|
| No worktree, no branch, no PR | Normal start. Continue above. |
| A stale worktree from a dead session, uncommitted changes | Read them. Salvage what is right; say in your handoff what you kept and discarded. |
| A pushed branch, no PR | `git worktree add` onto that branch instead of a new one, rebase on current trunk, continue from it. |
| An **open PR** | The previous session got further than the board shows. Assess it against the ticket, finish or fix it — do not open a second PR. |
| A **merged** PR | The work landed and the state write did not. Do not rebuild it. Comment saying so, hand back — the manager reconciles (`core/pm/skills/preflight.md` §0 step 3). |

**Push early once there is something real.** A local-only commit dies with the worktree; a
pushed branch survives it and lets the next worker continue instead of restarting.

---
