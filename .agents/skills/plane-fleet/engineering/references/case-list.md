# Case list: the definition of done for one ticket (trial: `fleet.trials.case_list`)

Only when the trial is on in the project config. Read by the PM, the tester's `case-list`
skill, the engineer's build skill and the tester's blind check. §4 applies only when
`fleet.trials.closed_retest` is on too.

(2026-11-20, one project, a 20 hour run: 22 of 38 tickets failed their first test, 35 failed
tests in all, and one ticket had 10 rework sessions. Most rounds did not find the same bug
again. They found something new, because "done" was never a fixed list and each retest brief
added checks.)

## 1. When and who

- Every ticket above "small" (about 150 changed lines, `engineering/references/ticket-rules.md`
  §2) gets a list before it is built. The PM spawns a tester for a case-list session
  (`engineering/tester/skills/case-list.md`): no slot, no build.
- The list is one ticket comment that starts with `CASE LIST:`. From then on it is the
  definition of done. The engineer builds to it, the tester runs it, and the PM's briefs point
  at it instead of restating cases.
- Gaps in the ticket found while writing it go to the PM as questions before the build, not to
  the tester after it. The PM answers them (`core/pm/skills/ruling.md`) or asks the owner, and
  the list is updated before the engineer starts.
- A list over about 25 cases means the ticket is too wide. The PM sends it back to the planner
  to split. One screen per UI ticket.

## 2. The table

| # | Case | State or input | Expected | How it is checked |
|---|---|---|---|---|

- Numbered, and the numbers never change. The handoff, the verdict and every retest refer to them.
- "How it is checked" is a real run: a command, a browser step, a DB read. Never "read the code".
- A screen starts with its state table: every state of the row or panel, and each transition
  between them, is a case.
- Each rule that holds across a screen (nothing moves, no raw code shown, one message per
  action) names the grid it holds over: widths, languages, modes, positions, and every engine
  in `fleet.client_engines`. One row per rule, with the axes listed, not one row per cell.
- The last row is `Regression:` the existing specs and flows a retest runs again.

## 3. Severity, for a finding outside the list

- **s1**: data loss, money, a wrong or duplicate send to a customer, security, a blocked main
  path. It blocks the PR.
- **s2**: a visible fault with a workaround.
- **s3**: polish.

s2 and s3 do not fail the PR. They go on one follow-up ticket in the same epic, named in the PR
body and in the verdict. The PM makes sure follow-ups land before the release that carries the
feature.

## 4. Closed retest (trial: `fleet.trials.closed_retest`)

Only when that trial is on too. A retest runs the failed cases and the list's regression row.
No new exploration. The PM's retest brief adds no checks: a new worry becomes a case on a
follow-up ticket. An s1 seen in passing is still reported, and still blocks.
