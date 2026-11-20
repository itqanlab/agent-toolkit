# PM · ruling

> Part of the PM role (`core/pm/role.md`). Read it before you post a `PM SCOPE DECISION:`. Paths
> written as `core/…` and `engineering/…` are relative to the fleet folder, three levels above
> this file.

## Rulings: name the source before you decide

A `PM SCOPE DECISION:` changes what the tester judges against, so a ruling made from memory is
a guess the next round pays for. (2026-11-20, one project: the PM's scope calls and retest
briefs added new checks each round, and the log had no cause to count them under.)

1. Name the contract or spec section and the design reference you read, and quote the line the
   ruling rests on.
2. No source: mark it `PM guess, to verify`. A tester or a scanner checks it first, or the owner
   decides when it is a design choice. Nothing goes back to an engineer on a guess.
3. A ruling that changes behaviour lists which existing tests are retargeted, and how the tester
   judges each one.

```
PM SCOPE DECISION: <what the criteria are now>
source: <contract or spec §> · design: <reference> · "<the quoted line>"
retargets: <test file › name> → <how it is judged now>
```

A `verify_fail` caused by a ruling or a PM brief is logged with `--cause pm_ruling`
(`core/pm/skills/spawn.md` §3 step 6). `fleet retro` counts them.
