# tester · case-list

> Part of the tester role (`engineering/tester/role.md`). Read it when the PM spawns you for a
> case-list session, before the build. Only when `fleet.trials.case_list` is on in the project
> config. Paths written as `core/…` and `engineering/…` are relative to the fleet folder, three
> levels above this file.

## Case-list session: no slot, no build

Input: one ticket id, no PR and no slot. Nothing is built yet, so there is nothing to be blind
to. Read the ticket, its `PM SCOPE DECISION:` comments, the contract or spec sections it names,
and the screen as it is on trunk.

1. Write the table in `engineering/references/case-list.md` §2: the state table for a screen,
   one grid row per rule (every engine in `fleet.client_engines`), and the regression row.
2. Post it as one ticket comment that starts with `CASE LIST:`.
3. A gap in the ticket (a state with no expected result, two lines that disagree, a rule with
   no grid) goes at the end of the comment as a `question:` line, and in your report. Don't
   answer it yourself.
4. More than about 25 cases: post it anyway and say `too wide` in the report.

Report one line, then stop:
`case list — PROJ-134 · 14 cases · grid: 3 widths × 2 languages × chromium · 2 questions · comment posted`
