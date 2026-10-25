# PM · deploy-and-done

> Part of the PM role (`core/pm/role.md`). Read it when a group merged: deploy, confirm CI/CD, Done, tell the client. Paths written as
> `core/…` and `engineering/…` are relative to the fleet folder, three levels above this file.

## 6) Deploy, confirm CI/CD, Done, notify — no smoke test

The engineer looked at it and the tester looked at it. What is left is making sure it shipped.
**You do not open the app and you do not click through it.**

1. **Deploy** per config (`deploy.environments` and its `note`). If dev auto-deploys on push,
   any manual script is break-glass only. Do not race the auto-deploy.
2. **Confirm CI/CD, not the feature:**
   - trunk CI green on the merge commit (`gh run list --branch <trunk>`), including the deploy job
   - the health endpoint returns **200, not 502**, and reports the commit you merged
   - migrations applied (from the deploy log or the health payload)
3. **All green** → each ticket in the train → `Done` (priority preserved), comment: merge commit,
   CI run, deployed commit.

   **A watcher waits for the named jobs to EXIST, then for them to finish.** Jobs are created
   one stage at a time, so "every job completed" is true for a moment after the first stage
   passes and before the e2e jobs appear. Check for the jobs by name (`ci.required_jobs`
   in config, for example lint, unit, API e2e, browser e2e, deploy) and treat a missing one as
   not done. A job that is `skipped` by design (for example, the browser suite on a PR that
   doesn't affect it) counts as done.
   (2026-09-30: a watcher exited on that race and re-queued held runs too early.)

   **"Completed" is not "green".** A watcher loop must test `conclusion == success` explicitly,
   and you read the conclusion before any `Done` write. (2026-09-29: a watcher exited on
   `completed:failure`, and the PM set two tickets `Done` before reading it. Caught and reversed
   within a minute, but that's how a failed trunk gets reported to the client.)

   **Dev health matching the commit does NOT prove CI passed.** A platform that auto-deploys
   dev on every push does so even when trunk CI fails and its deploy job is skipped. So dev can be
   running code that failed typecheck. Always check the trunk CI conclusion, not just health.

   **A red trunk after merging a build-config or project-reference change: suspect the
   runner's build cache first.** Typecheck can read stale built declaration files from a
   persistent runner cache (`ci.runner_cache` in config): "no exported member" errors for
   exports that exist. Reproduce locally with a fresh cache. If clean trunk passes, move the
   runner cache aside (`mv` with a timestamp, never `rm`, and only when no job is running) and
   `gh run rerun --failed`. (Seen twice in one month.)
4. **Notify the client** — you now own this (`client` block in config;
   `engineering/references/notify.md` for hosting and sending). **One message
   per group** (owner, 2026-10-01): once every ticket in the group is `Done`, send a single
   message that lists each improvement the client will notice, one plain-language line each, no
   ticket ids. Attach the client-ready screenshots the testers attached to those tickets; you
   never capture one yourself. Tickets with no user-visible surface (CI, refactors, internal
   tooling) are left out of the message, and a group with none of those sends nothing. Record on
   each included ticket that it went out, and in which message.

   **Send it directly.** It's an update notification, so don't read the thread first and don't
   hold it (owner, 2026-10-01). Send as soon as the ticket is `Done`.

   **Tidy the main checkout after every group.** From the repo root, run
   `engineering/scripts/git-tidy.sh --apply`. It fast-forwards the trunk
   and main, and deletes only local branches whose every commit is already in the trunk by
   content. It never touches a dirty tree, local commits, or a branch checked out in a live
   worktree. It never drops a stash: it lists them. Put any `KEEP:` line or stash in your next
   report to the owner, once, with what it is. Don't decide for them. (2026-10-02: no one
   tidied, and the checkout reached 96 local branches, 186 commits behind, and 3 stashes up to
   4 months old.)

   **Close parents whose children are all done.** After each `Done` write, check the ticket's
   `parent`. If every child of that parent is `Done` or `Cancelled`, set the parent `Done` with a
   comment listing the children. (2026-10-01: a parent sat `In Progress` with every child done.)
5. **Anything red** → do not set `Done`, do not message the client:
   - CI red on trunk → `core/pm/skills/stop-the-line.md` §1 (stop the line)
   - deploy failed / 502 / wrong commit / migration failed → a real blocker. Fix it as ops
     (re-run, break-glass script) or revert the train, file `urgent` Rework, tell the user.

> **Gate:** never merge a new train while the previous train is `Merged` but not `Done`. That is
> a deploy you have not confirmed, and piling more on top makes a failure impossible to pin to
> one PR. The tell: you are about to run `gh pr merge` and tickets are still sitting in `Merged`.

**Then go straight back to `core/pm/skills/pick.md` §2.** No summary-and-wait.

---
