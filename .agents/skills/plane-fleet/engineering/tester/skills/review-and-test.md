# tester · review-and-test

> Part of the tester role (`engineering/tester/role.md`). Read it when your Phase A verdict is written: Phase B, review the diff and write the tests. Paths written as
> `core/…` and `engineering/…` are relative to the fleet folder, three levels above this file.

## 2) Phase B — code review and tests (now you may read the diff)

`gh pr diff <n>`, the PR description, the handoff comment, the source.

**Review for what Phase A cannot see:**
- logic the criteria did not exercise: other callers of a changed function, other roles, other
  branches of a conditional, error paths
- the repo's rules: `CLAUDE.md`, `contracts/`, module boundaries, i18n (no hard-coded strings,
  every key resolves in both locales), the error envelope, permissions
- stubs, TODOs, dead code, a `?? ''` fallback that reaches the database as an empty id
- a gate quietly widened (budget, threshold, lint disable, skipped test) — an automatic Rework

**Write the tests that should exist and don't.** Unit/spec tests next to the code, or a
browser spec in the e2e folder (`test.e2e_dir`) for a user flow. Rules:

- **Test files only.** `*.spec.ts`, e2e specs, test fixtures/helpers. If making a test pass needs
  a product-code change, that is a finding, not a fix.
- Small logical commits, conventional style: `test(orders): cover zero-quantity line (PROJ-57)`.
- Run only the specs you wrote while iterating (`--skipNxCache`, `NX_DAEMON=false`). The full
  gate runs once, through the pre-push hook, when you push. Don't also run it by hand first.
  Check `ls .husky/_` first and run `npx husky` if it's missing.
- **Push them to the PR branch** (`git push origin test/<...>:<branch>`), including a test that
  fails because it exposed a bug. A failing test is the clearest spec a rework engineer can get.
  If the branch moved under you, rebase your test commits onto it; never force-push over the
  engineer's commits.
- Never delete, skip or weaken an existing test.

**Run the existing browser specs for what this PR touches, before you approve.** When PR CI
does not run the browser suite (it runs on trunk after the PM merges a group), you are the last
browser check before merge. In your slot, run the spec files for every screen the diff touches
(`test.e2e_run` in config, with your slot's ports), plus the specs you wrote. Put the command
and the pass count in your APPROVED comment. A PR that changes shared UI (`fleet.shared_ui_paths`:
the shell, a shared table, dialog or form control) touches too much to pick specs by hand. Say so in your APPROVED comment
("shared UI: needs the full browser suite") so the PM checks it in the group PR's run. Do not mark
the PR ready to get that run yourself.

**Do not run the full server or browser suite yourself** (owner, 2026-10-15). The PM's group
PR runs both in CI, with the e2e label set before the PR is marked ready, and that run is the
full check. Run your PR's own specs, the specs for the screens and endpoints the diff touches,
and the specs whose assertions hit text or keys the diff changed (grep for them). A full local
run costs 15 to 20 minutes on one worker, and in the 2026-10-14 run testers ran it once or
twice per ticket while the group PR ran it again: one of the main reasons sessions took 3 hours.

**Browser (e2e) specs: keep adding them, and write them so the suite can be sharded.** The owner's
decision (2026-10-01) is to keep growing e2e coverage and fix the speed with sharding, which only
works if specs don't depend on each other. So an e2e spec you add:
- lives in the spec folder the repo uses (`test.e2e_spec_dir`). Don't add a new test project
  for one app: every project reruns the whole suite (an extra project once doubled it).
- seeds its own rows with names unique to the spec (ticket id plus a random suffix), and never
  relies on rows another spec created, or on running in a particular order
- switches locale or viewport inside the spec when it needs English or a small screen
- extends an existing spec file for the same screen before starting a new one. One file per
  screen keeps the suite easy to shard.

---
