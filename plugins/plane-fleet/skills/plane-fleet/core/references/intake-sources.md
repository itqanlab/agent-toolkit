# Intake sources

> Read by the PM at run start and once per loop (`core/pm/skills/preflight.md`, `core/pm/skills/pick.md`),
> and when setting up a project. The tool is `core/scripts/fleet intake` (`fleetintake.py`).

Some work never reaches the board by itself. An error tracker emails each new production error
and nobody files it. An intake source is a feed the fleet reads on its own. Each new item goes to
the planner, which investigates it and writes a normal ticket. Then it waits in the queue by
priority like any other ticket.

The fleet pulls. Nothing pushes into Plane: no webhook, no Plane key on a server, and agents
still reach Plane only through the MCP.

(2026-11-20, one project: Sentry had emailed every new production issue for five weeks. Of 14
open issues, none had a ticket. Two of them had hit 11 and 9 staff members.)

## Sentry, built in

On whenever the project config has a `sentry` block. Off when it doesn't. `fleet intake` warns
when the repo ships a Sentry SDK (`@sentry/*` in `package.json`, `sentry-sdk` for Python,
`sentry-ruby`, `sentry-go`) and the block is missing. The PM passes that warning to the owner
once, at run start.

```jsonc
"sentry": {
  "host": "de.sentry.io",            // the region host; sentry.io for US
  "org": "acme",
  "projects": ["acme-web", "acme-api"],  // REQUIRED. Only these are read, never the whole org
  "environment": "production",       // the env name the app sends; the issues of no other env are read
  "token_env": "SENTRY_AUTH_TOKEN",  // read the token from this env var ...
  "token_file": "~/.config/plane-fleet/secrets/sentry-acme",   // ... or this file, mode 600 (per-user override only)
  "window_days": 7,                  // a new issue qualifies when first seen this recently
  "min_users": 2, "min_events": 5,   // ... and it hit this many users or events
  "always": ["acme-api"],            // projects where any new issue qualifies (a server error is rarely noise)
  "urgent_users": 5,                 // this many users makes it urgent
  "urgent_paths": ["/payments", "/checkout"],   // a culprit or title containing one of these makes it urgent
  "ignore": ["ResizeObserver loop"], // title substrings, issue ids or short ids never offered
  "max_per_run": 5                   // items handed to the planner per pass; the rest wait
}
```

Put the non-secret part in `.plane/config.json` so every machine reads the same projects. Put
`token_file` (or nothing, and the env var) in the per-user override. A token never goes in the
repo. A token file that others can read gets a warning.

What qualifies: unresolved, in `environment`, in one of `projects`, first seen inside
`window_days` or marked regressed by Sentry, and over a threshold (or in `always`), and not in
`ignore`. Severity: `urgent` at `urgent_users` or on an `urgent_paths` match, `high` for
`always` projects, `min_users` or a regression, `medium` otherwise.

Each item's `evidence` holds the Sentry link, counts, first and last seen, release, URL path,
the last four in-app frames as `file:line function`, and the last four breadcrumbs (category,
method, status and path only). Query strings are dropped. Emails, phone-like numbers and
`token=`/`key=` values are redacted. Console text never goes in.

## Command sources

For any other feed: `fleet.intake_sources`, a list.

```jsonc
"fleet": {
  "intake_sources": [
    { "name": "uptime", "command": "node tools/uptime/incidents.mjs", "external_source": "uptime",
      "max_per_run": 3, "resolve_command": "node tools/uptime/close.mjs" }
  ]
}
```

The command runs from the repo root with a 120 second limit. It is read-only and prints:

```json
{ "items": [ { "external_id": "inc-42", "title": "API p95 over 2 s on /orders", "url": "https://…",
               "severity": "urgent|high|medium|low", "evidence": "free text, no secrets",
               "regression_of": null } ] }
```

An item with no `external_id` or `title` is dropped. An unknown severity becomes `medium`.
Evidence is scrubbed the same way as Sentry's. A non-zero exit, bad JSON or a timeout marks the
source failed for that pass. It never fails the pass or blocks a pick. `resolve_command` gets
`<external_id> <release>` as arguments.

## The commands

| Command | Does |
|---|---|
| `fleet intake` | every source's new items as JSON: `{sources: [{name, external_source, ok, error, items, skipped_filed, over_cap}], warnings}`. Exit 0 even when a source fails |
| `fleet intake check` | one line per source: on, its scope, whether it answered. Exit 1 when one failed |
| `fleet intake mark <source> <id> --ticket T` | remembers the item was filed, so it is not offered again |
| `fleet intake resolve <source> <id> --release SHA [--ticket T]` | tells the source the fix shipped. Sentry: resolved in that release, plus a note naming the ticket |

Local memory lives in `{state_home}/state/intake-<project>.json`. The board is still the truth.
Before filing, the PM checks Plane for the `external_id`, so a lost state file never makes a
duplicate. An item that was filed, resolved and came back is offered again, with
`regression_of` set to the old ticket.

## The PM's loop

1. **Run start**, after the config is read: `fleet intake check`. Put each `FAIL` line and any
   `warning:` line in the opening summary. No sources and no warning: skip intake for the run.
2. **Each pass** (run start, then once per loop before pre-pick triage): `fleet intake`. No
   items: carry on. Never stop the run over a failed source.
3. **Dedupe on the board**, one call per item:
   `workitem(action="list", project_id=P, external_source=<src>, external_id=<id>, fields="sequence_id,state")`.
   An open ticket exists: run `fleet intake mark` with it and drop the item. On Plane MCP
   versions without the fix for this lookup, a match comes back as a validation error whose
   text names the row (`'sequence_id': 1558`). Read that as a match. `HTTP 404` means none.
4. **Plan the rest in one planner spawn per pass**, never one per item. The brief holds the items'
   JSON. The planner investigates each against the repo (`core/planner/skills/write-ticket.md`),
   may merge items with one root cause into one ticket (listing every external id in the body),
   and may drop an item it can show is noise. It says why, and the id goes in that source's
   `ignore`. Severity sets the priority. A regression links the old ticket with `relates_to`.
5. **fleet-board files** each ticket in Todo with `external_source` and `external_id` set and the
   source link in the body. Then `fleet intake mark` for every external id it covers.
6. **After deploy**, for each Done ticket that carries an `external_source`: `fleet intake resolve
   <source> <external_id> --release <deployed sha> --ticket <PROJ-N>` (`core/pm/skills/deploy-and-done.md` §6).
   If the error comes back, Sentry marks it regressed and the next pass offers it again.
