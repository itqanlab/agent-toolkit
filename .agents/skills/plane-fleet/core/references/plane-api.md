# Plane through the MCP: what works, and what a board read costs

> **Plane access is MCP only.** Every Plane read and write goes through the `plane` MCP
> server's tools. No curl, no inline Python, no scripts against the Plane API. If no `plane`
> tools are available, stop and ask the user to enable or reconnect the plane MCP server.
> A capability the MCP lacks becomes an issue on the MCP server's tracker (`plane.mcp_issues`
> in config), not a workaround.

## Current state (2026-10-17): the plugin's Plane MCP server, Plane Community 1.4.2

The plugin declares a Plane MCP server named `plane` (see the plugin README). Its tools take an
`action`: `workitem(action="update", ...)`. `P` below is the project id from `.plane/config.json`.

A running MCP keeps the code it started with. After the fork merges something new, the user
has to reconnect the plane MCP server before the new actions exist in a session. An
"unknown action" error on one of the calls below means the server is old, not that the call
is wrong. Report it; do not route around it.

| Need | Call | Notes |
| --- | --- | --- |
| census | `workitem(action="count", project_id=P, group_by="state_id")` | groups by state NAME, ~200 bytes. Also `state__group`, `priority` |
| pick list | `workitem(action="list", project_id=P, pql='state IN ("Todo","Rework") AND priority IN ("urgent","high")', per_page=N, fields="sequence_id,priority,name")` | priority order (urgent first), newest first within a priority. `per_page` caps after sorting; `matched` is the total before the cap |
| other orders | same, with `order_by` = `-updated_at`, `updated_at`, `sequence_id` or `-sequence_id` | anything else is refused with the list |
| stale tickets | `workitem(action="list", project_id=P, pql='state NOT IN ("Done","Cancelled") AND updated_at < "<today minus N days>"', fields="sequence_id,priority,name")` | `<`, `<=`, `>`, `>=` on `updated_at` / `created_at`; a bare date is midnight UTC |
| one ticket's header | `workitem(action="retrieve_by_identifier", workitem_identifier="PROJ-N", fields="name,state,priority,updated_at", expand="state")` | |
| one ticket's body | `workitem(action="body", workitem_identifier="PROJ-N", chars=1500)` | plain text with state name, priority, `text_chars`, `truncated`. `chars=0` for all |
| pre-pick triage | `workitem(action="triage", workitem_identifiers=["A","B"], path_prefixes=["apps","libs"], comments=true)` | up to 25 tickets. Plane facts only: `text_chars`, `keywords`, `paths`, `decision_words`, `vague_scope`, and with comments `decision_comments`, `comments_after_update`. Repo side: `engineering/scripts/repo-scan.sh` |
| states | `state(action="list", project_id=P)` | compact rows |
| state change | `workitem(action="update", workitem_identifier="PROJ-N", state="In Review")` | state by name. Reply has `state_name` and `description_escaped`. A state-only update sends only the state, so priority is never touched |
| several changes | `workitem(action="update", workitem_identifier="PROJ-N", state="In Review", assignees=["dev@example.com"], target_date="2026-10-21")` | ONE call. Decide every field before you send it; a second update for a forgotten field is waste. Assignees take a uuid, an email or a display name (PMCP-18); an unknown name is refused with the members listed. The reply echoes every field the call set, as stored (PMCP-17) |
| comment | `workitem_comment(action="create", workitem_identifier="PROJ-N", comment_html="<p>..</p>")` | reply is `{id, workitem, created_at, comment_chars, comment_escaped}`, not an echo |
| relations | `workitem_relation(action="create" / "list" / "delete", ...)` | create and list work through the API. Delete goes through a bot web session inside the MCP, since Plane 1.4.2 has no API route for it. Both work on our Plane |
| search | `workitem(action="search", query=...)` | whole workspace, no project id needed; rows carry the project identifier and `sequence_id`. Use it OR a `list`, never both for the same lookup |
| rows | `workitem(action="list")` returns compact rows by default | `fields=all` for every field |
| rate limit | 429s are retried inside the MCP | our Plane allows 600/minute per key |

### How `pql` works here

This Plane edition refuses `pql`. The fork pages the project and applies the filter itself;
the reply says `pql_applied: client`. Supported: `=`, `!=`, `IN`, `NOT IN`, joined by `AND`,
on state (names are fine), priority, parent, type_id, sequence_id, is_draft, plus the date
comparisons on `updated_at` / `created_at`. A filter outside that set is an error, not a
silent full board. Still prove a filter you have not used before: every returned row should
carry the value you asked for.

## Writing: `description_html` and `comment_html` take RAW HTML

Send real tags. **Do not HTML-escape them.** If you send `&lt;p&gt;`, Plane stores the
entities verbatim and the ticket or comment renders as visible markup. It is not rejected,
nothing errors, and the write "succeeds".

```
comment_html: "<h3>Findings</h3><p>Blocked by <code>PROJ-144</code>.</p>"   ✅
comment_html: "&lt;h3&gt;Findings&lt;/h3&gt;"                                 ❌ renders as text
```

Escape **only** literal angle brackets you want the reader to see, such as `<app-card>` inside
a real `<code>` tag: `<code>&lt;app-card&gt;</code>`.

**Check the reply every time.** Update replies carry `description_escaped` and comment replies
carry `comment_escaped`, with a warning when Plane stored the markup as text. If either is
true, fix it at once with the same content unescaped.

## Writes still have to be verified

Read back anything the picker depends on. After setting relations, call
`workitem_relation(action="list")` and match the related ids against what you sent. Skill §1
skips a ticket whose `blocked_by` target is not Done, and prose in a description does nothing.

**An error is never "no relations".** A clean list means none; an error means you have not
read them yet. If you cannot read them, treat the ticket as blocked and skip it.

The same goes for any write: confirm a state change shows the new `state_name`, and confirm a
field you did not mean to touch was not changed.

**Check the echo before you read again.** `create`, `update`, `manage_assignee` and
`manage_label` reply with every field the call set, as Plane stored it (PMCP-17). Compare
those values with what you sent; that is the verification. Read the item again only for
something the echo cannot show, such as relations or comments. On an MCP older than PMCP-17
the reply has no `assignees` or dates, so a read-back is still needed there.

## Rate limits, and why a throttled scan changes the answer

Measured 2026-08-18 repairing 234 tickets (at the old 60/minute limit). The MCP now retries
429s, but bulk sweeps still need the discipline.

**The dangerous part is not the error. It is what an unhandled error looks like.** An
unthrottled sweep of every issue's comments reported `281 comments, 68 broken`. 116 of 234
fetches had 429'd and been counted as "nothing there". The same sweep, paced, read **481
comments and found 104**. A scan that cannot read half the board looks like a board that is
half clean, and the smaller number is the one that looks reassuring.

For any bulk operation through the MCP:

- **Count your failures and print them.** A sweep that does not say how many calls failed
  cannot be trusted.
- **Treat a failed call as UNKNOWN, never as EMPTY.**
- **Never repair from a scan that had errors.** Re-scan clean, then write.
- **Verify writes by re-reading, not from your own success list.** After a partial run, 37
  writes were recorded as failed; re-reading showed 36 still broken. One had landed despite
  reporting an error.
- **Back up before bulk writes.** Save the original rows to a file first.
- Pace bulk writes at roughly one a second even with retries.

## The general lesson

A filter that is ignored looks exactly like a filter that matched everything, and a field
that was not returned looks exactly like a field that is empty. Both fail silently and both
produce confident wrong surveys. Before acting on a filtered or sparse query, prove it did
what you asked: check that a row you know is excluded is absent, and that the field you are
testing is non-null somewhere. A unanimous answer (0 of N, or N of N) is the tell.
