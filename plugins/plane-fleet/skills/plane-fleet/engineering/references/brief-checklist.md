# Brief checklist — defect classes that keep coming back

Each item below is a kind of defect that sent tickets back to rework more than once. The PM
copies the items that apply to a ticket into its engineer brief, under `CHECKLIST:`, numbered as
here. The engineer checks each one before the handoff and names in the handoff which ones it
checked (`checklist: 1, 2, 4, 5, 15`) and what it found. An item that does not apply is left out
of the brief, not marked N/A. A project can keep its own extra items in the per-user state
folder and the PM adds those too.

Item 21 sits in "Before writing code" but is numbered last, so the numbers already in briefs and
handoffs stay the same. The sections are not in numeric order for that reason.

(2026-11-04, one project: 9 of 16 tested tickets went to rework in one run. Every item here came
back at least twice.)

## Before writing code

1. **Find every entry point of the shape you change.** Grep services, controllers, jobs, other
   clients' endpoints and imports. Fix it in the one shared function every caller goes
   through. List each path with `file:line` in the handoff. Fix one case and the next review
   finds its sibling.
2. **Any list of "all X" comes from a grep, never from memory.** Entities, actions, statuses,
   writers: paste the search you ran and what it returned.
3. **Read every `PM SCOPE DECISION:` on the ticket.** If the ticket needs something you cannot
   get (production data, a decision, a schema go-ahead, a guard exception), stop and ask before
   you write code. Do not guess.
4. **Know who sees what.** The brief says, per role, who sees which screen, button and field.
   If it does not and the ticket changes what a role can see or do, ask the PM before you build.
21. **A rule about whether something may happen, or who may see or do something, gets one
    function that every caller goes through.** List the callers by grep in the findings comment
    before you code. A check added per path sends the next review to the next path.

## UI tickets

5. **Requests read the filters the user applied**, a snapshot taken on Apply, never the live
   picker or form value.
6. **One latest-request guard per piece of component state.** Every request that writes state
   goes through it (cancel the old request, or a sequence id). A late or failed older response
   never overwrites newer state, error banners included.
7. **Values that arrive late from a child control are read at click time**, not from a copy
   taken earlier.
8. **The shared UI kit's own rules** (its accessibility attributes, which inputs may be native,
   its style tokens): run the shared UI kit's own tests before you push, and those of any second
   kit the change touches.
9. **A change to what a screen shows makes old specs stale.** Grep every end-to-end spec for the
   text or figure you remove or move, and update those specs in the same PR.

## Money tickets

10. **Money comes from exact stored totals** (line totals, ledger rows), never from a rounded
    unit price times a quantity.
11. **Swaps and exchanges: try an even, a cheaper and a dearer one.** A payment carried over
    from the first sale never counts twice.
12. **Never change when money or stock moves** unless the ticket says so. A return that waits
    for the goods to arrive keeps waiting.

## Dates and concurrency

13. **Dates in the business timezone**, converted in the query or with the project's shared
    helper, never with an offset added by hand. Test both sides of midnight and of a week or
    month boundary.
14. **An offer, rule or window past its end date never blocks anything.** Freeze the clock in
    date tests so they do not fail when the calendar moves on.
15. **Two locks, one order.** A path that takes two locks takes them in the same order as every
    other path that takes them. Write a real concurrent test.
16. **A no-op write writes nothing**: no row, no history entry, no audit event.

## Review before handoff

17. **Run the focused review with the project's configured strong reviewer**, with the prompt
    from your brief, and loop until a pass is clean (`engineering/engineer/skills/open-pr.md`
    §3b). If that reviewer is out of usage, say so in the handoff. The PM then runs another
    strong reviewer before any tester starts.

## Testers

18. **A resource refusal is not a rework reason**, and neither is a criterion no agent can
    check (a physical phone, a browser's own password dropdown). Report it as not demonstrated
    and judge the rest.

## PRs and CI

19. **The ticket PR opens as a draft and stays a draft.** Never mark it ready and never add the
    e2e label to it. CI runs on the group PR, and the full e2e suite on the release PR
    (`engineering/references/standing-brief.md`).
20. **One full gate at a time on the machine.** Take the gate lock before you push
    (`engineering/references/standing-brief.md`, "Run each check once per commit"). Never write
    a gate result line into a log by hand.
