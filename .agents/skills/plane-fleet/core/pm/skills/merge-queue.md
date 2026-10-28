# PM · merge-queue

> Part of the PM role (`core/pm/role.md`). Read it when approved PRs wait: you alone merge, in groups. Paths written as
> `core/…` and `engineering/…` are relative to the fleet folder, three levels above this file.

## 5) Merge queue — you alone merge

A PR is eligible when **all** hold: ticket `Approved`, label `qa-approved` present, CI green on
its latest commit, trunk green (`core/pm/skills/stop-the-line.md` §1), and, for a schema PR, no other schema PR in
the same train.

**Schema PRs, one per train.** Schema tickets build in parallel (`core/pm/skills/pick.md` §2), so
several schema PRs can be approved at once. Land the oldest first, in a train of its own. Before
the next one merges, its branch is rebased onto the new trunk and its migration folder is
re-stamped to sort after trunk's latest; then it runs the repo's deploy-style migrate on a fresh
slot DB and the schema validator, and its CI goes green again. A clean rebase with only the
re-stamp is a mechanical step and yours. A conflict inside the schema file is an engineer lane.

1. **Order:** dependencies first, then oldest-approved, then by area.
2. **Land one at a time**, each on the trunk the previous one produced:
   ```bash
   gh pr merge <n> --merge --delete-branch
   git checkout <trunk> && git fetch origin && git reset --hard origin/<trunk>
   ```
   **A branch another open PR is based on is never deleted at merge.** Check first:
   `gh pr list --state open --base <head branch of n>`. If anything is listed, merge `<n>`
   without `--delete-branch`, move each listed PR to the trunk with
   `gh pr edit <m> --base <trunk>`, and delete the branch only after that. GitHub closes a PR
   whose base branch is deleted, and a closed PR cannot be retargeted, only re-filed as a new
   PR (2026-10-17: a stacked PR closed this way and had to be re-filed).
   For each next PR: `gh pr update-branch <n>`, then **wait for its CI to go green again** before
   merging. This is the one place anyone waits for CI, and it is you.
3. **Conflicts:** a mechanical rebase is yours. Anything that changes behaviour is not — send the
   ticket to `Rework` with a comment naming the conflicting PR, and remove `qa-approved`.
   **Shared-registry conflicts are mechanical, and they are yours** (i18n JSON, error codes,
   audit actions, DTOs, permission matrix + spec + contract, module providers, route table).
   Merge the trunk into the PR branch in a scratch worktree, keep both sides' additions, then
   **dedupe**: git auto-merges two PRs that each added the same entry into a duplicate without
   flagging a conflict (2026-10-08: `hr:self` landed twice in permission-matrix.ts, the
   contract table and both settings.json files). `grep -c` each key you kept. Then run
   typecheck + the affected tests with `--skipNxCache`, and push through the hook. Expect it:
   in an area where every ticket adds a permission, each merge conflicts the next PR.
4. **Tester commits land with the PR.** If the tester pushed tests after approving, CI has to be
   green with them included.
5. **Write each ticket → `Merged` right after its own merge**, comment naming the merge commit.
6. Merge up to `fleet.merge_train_size`, then let the deploy settle (`core/pm/skills/deploy-and-done.md` §6) before the next train.

**Draft-only fleets: one group PR, and it is the full check** (owner, 2026-10-13 and
2026-10-15). When engineers open drafts and testers leave them draft, the PM builds
`release/group-<date>-<n>` from about 10 approved branches, runs the pre-push gate and a Codex
review (`codex review "<instructions naming the base>"`; `--base` cannot be combined with a
prompt), and opens ONE PR into the trunk. That PR is where the whole server and browser suites
run, so testers no longer run them per ticket (the tester role). To make sure they really run:
- open the group PR **as a draft**, add the e2e label, and only then `gh pr ready`. A label
  passed to `gh pr create --label` is applied after the opened event, so CI never sees it
  (2026-10-14: the full browser suite was skipped on group 1, and 3 reds surfaced on develop).
- check the run's scope step printed the label as present (`HAS_LABEL: true` on this repo)
  and that the browser job reads SUCCESS, not SKIPPED, before merging.
- a red group PR: match the failing spec to its PR (`gh pr view --json files`), drop that
  branch from the group, rebuild, and send its ticket to Rework.
- a red group PR you fix in place instead: split the failures by effort. The easy ones (a
  snapshot, a test's own race) are pushed first, in one lane. Each hard investigation gets its
  own lane, so it never holds up the easy fixes. Check on every group-fix lane at 30 minutes.
  While one runs, allow at most one other heavy session on the machine. (2026-10-27: a group
  of 8 took about 4.5 hours, and the work itself took about 1.5. A 20-minute fix waited
  behind a 3-hour investigation in the same lane, on a machine at a load of 36 to 61, and the
  PM first asked for a status 2.5 hours in.)

**Merge in groups of about 5 when the browser suite only runs on trunk.** Many repos keep PR
CI short (affected lint, typecheck, unit and API tests) and run the browser e2e suite only on
the trunk push after a merge, unless the PR carries the full-e2e label (`ci.e2e_label` in
config). Then "CI green" on a PR doesn't include the browser suite, and the trunk run after a
group is where it gets checked:
- Pick up to ~5 approved PRs with green PR CI and no shared files, and merge them back to back.
  One develop run covers them all.
- Keep a group to ~5 PRs. If trunk goes red in the browser suite, the failing spec names the screen;
  match it to the PR in the group that touched that screen (`gh pr view --json files`). Revert
  only that PR, send its ticket to `Rework`, and let the rest of the group stand. Unclear →
  revert the whole group and re-merge it in halves.
- A PR that changed shared UI goes in a group of its own, or carries the e2e label.
- **Two PRs that change the same shared component never go in one group.** Shared means
  the paths in `fleet.shared_ui_paths` (for example the UI library, the form contract, the table
  and field components). Hold the second PR until the first group's trunk run is green.
  2026-10-05: three PRs sharing a form component each passed testing on their own, then broke
  trunk together and all three were reverted.
- **A PR that adds or changes a browser e2e spec needs a green e2e-labelled PR run before it
  merges.** If the suite runs on several workers, a local pass on one worker doesn't count. The
  label must be on the PR **before** the push that triggers the run: adding it afterwards
  doesn't re-run CI, and the e2e job shows `SKIPPED`. Label first, then push or
  `gh pr update-branch`. Check that the e2e job reads SUCCESS, not SKIPPED, before merging.
- **When trunk goes red, check the failing spec against the group with `gh pr view --json
  files` before reverting.** Revert the PR that owns that spec or screen. 2026-10-05: the PM
  reverted a PR on a guess; the failing spec belonged to another PR in the group.

Measured basis: with the browser suite on every PR, 10 approved tickets needed about 3 hours of
single-runner time to reach dev. With it on develop only, it's about 1 hour.

**Batch the train. Don't merge the moment one PR is ready.** Each merge costs a full trunk CI run
plus a deploy, about 15 minutes on the single runner, and until it's `Done` it blocks the next
train. If another PR is in `Testing` and its tester started more than ~10 minutes ago, hold the
approved one and merge both together: one trunk CI, one deploy, one confirmation. Measured
2026-09-29: merging two approved PRs one at a time cost two trunk runs and two deploy waits, about
35 minutes. Holding the first for 11 minutes would have saved most of that. Don't hold longer than
~20 minutes, and never hold for a PR still with an engineer.

**Skip `update-branch` when the PRs don't share files.** For the second and later PRs in a train,
compare its changed files with those of every PR merged ahead of it (`gh pr view <n> --json
files`). If there's no overlap and GitHub reports `mergeable: MERGEABLE`, merge it directly
without updating the branch and re-running PR CI. Trunk CI after the train tests the combined
code, and a red trunk still stops the line (`core/pm/skills/stop-the-line.md` §1). Update and re-run only when files overlap, or
when GitHub says the branch is behind in a way that blocks the merge. Measured 2026-09-29: an
`update-branch` on disjoint files cost a 22-minute PR CI rerun.

**Merge the whole train back to back, so trunk runs once.** Merging PRs a few minutes apart
starts a separate trunk run for each one. Land them together, then check for superseded trunk runs:

```bash
gh run list --branch <trunk> --status queued --json databaseId,headSha,createdAt
```

A queued run for an older merge commit is redundant: the newest run tests everything it would
test, and it also carries the deploy. Cancel it (`gh run cancel <id>`) and track only the newest
run for `Done`. Never cancel a run that has **started**, because it may be mid-deploy. Say which
run you cancelled and which one you're tracking. (Done by hand on 2026-09-30: a queued run was cancelled because the next merge's run
contained it. That freed about 20 runner minutes.)

**Let trunk and urgent fixes jump the runner queue.** The single runner serves jobs first come,
first served, and a job only joins the queue once the job before it in its run finishes. So a
trunk run's e2e jobs, or an urgent fix's CI, can sit behind a long tail of PR runs. To move one
to the front:
- cancel queued PR CI runs that have no job **running** right now (runs whose first job already
  passed count too), and save their ids
- when the priority run is done, `gh run rerun <id> --failed` for each saved one. That re-runs
  only the cancelled jobs and keeps the ones that passed.
Never cancel a job that is running. (2026-09-30: used twice. A trunk run and an urgent fix each waited behind 6+ PR runs.)

---
