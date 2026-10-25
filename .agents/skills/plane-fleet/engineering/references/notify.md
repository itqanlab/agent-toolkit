# Client notification channels

Driven by `client.channel` in `.plane/config.json`. Send autonomously after a ticket is
verified live — never ask approval, never skip. **Every message carries the §7.5 screenshot**
— see "Screenshots" below for capture, hosting and cleanup.

## `mcp-message`

Send through a messaging MCP server named in `client.mcp_server`. Look up its send tool once
(`client.send_tool`, or discover it from the server's tool list) and pass:
`client.account_id`, `client.conversation_id`, the text, and the screenshot URL.

Worked example: a social-inbox MCP that proxies WhatsApp. Such servers often expose a generic
`call_tool` instead of one tool per action:

```
<server>.search_tools({query: "send inbox message"})                 // discover
<server>.call_tool({
  name: "messages_send_inbox_message",
  arguments: {
    account_id: "<client.account_id>",
    conversation_id: "<client.conversation_id>",
    message: "<text>",
    attachment_url: "<public https URL of the screenshot>",            // always
    attachment_type: "image"
  }
})                                                                      // -> message id
```

Lessons that hold for WhatsApp through any provider:
- `attachment_url` must be **publicly fetchable**: WhatsApp downloads it server-side at send
  time, so a localhost or file:// path silently fails. Image and text go in the same call.
- Free-form text only works inside the **24-hour customer-service window** (the client wrote
  within 24h). Outside it, free-form is rejected: use an approved template.
- A success response is not delivery. Read the thread back and check the delivery status.

## A messaging skill

If `client.channel` names a skill that sends messages (for example one that handles the
24-hour window itself), call that skill with the recipient, the text and the image URL.

## `none`

No client configured → skip §8 without comment.

---

## Screenshots

Every client message ships with a picture of the change (§7.5 / §8). Three steps, and the
third is not optional.

### 1. Capture to disk

The `claude-in-chrome` screenshot action **cannot be used for this**. Its `save_to_disk`
attaches the image to the chat for the user; it does not hand back a path Bash or an upload
tool can read. Drive the app with it, then re-take the shot with a headless browser that
writes a real file:

```js
// run from the repo root so `playwright` resolves; it is usually already a devDependency
const { chromium } = require('playwright');
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
await p.goto('<app>/login');
// log in with the seeded role that actually sees the feature, then:
await p.goto('<app>/<the page the ticket changed>');
await p.waitForLoadState('networkidle');
await p.screenshot({ path: '<scratchpad>/<ticket>-<what>.png' });
await b.close();
```

Rules for the image itself:
- Log in as the **role the client cares about**, not an admin, if they see different screens.
- Wait for real data — never ship a skeleton or a spinner.
- Full page or a tight crop of the changed area. No devtools, no browser chrome, no
  scratch/test records visible with obviously fake names if you can avoid it.
- If the change is a state transition (before → after), send the **after**; the client knows
  what "before" looked like, they lived with it.

### Shortcut: the screenshot is already on the Plane ticket (fleet flow)

When the tester attached a client-ready screenshot to the ticket (the PM flow), skip
steps 1 to 3. `workitem_attachment(action="download_url")` returns a presigned HTTPS link that works
for about an hour without auth. Check it with `curl` (200, `image/png`), look at the image
yourself, and pass it as `attachment_url`. The messaging service keeps its own copy, and the link expires on
its own, so there's nothing to clean up.

### 2. Host it publicly, temporarily

The messaging service fetches the URL itself, so it must be reachable from the internet. Default pattern:
serve it from the deployed app's own static root, which is already public and already TLS.
For an nginx-served client container:

```bash
NAME="shot-$(openssl rand -hex 16).png"          # unguessable — see the CDN warning below
docker exec <client-container> mkdir -p /usr/share/nginx/html/tmp-shots
# upload the PNG to the host, then:
docker cp /tmp/$NAME <client-container>:/usr/share/nginx/html/tmp-shots/$NAME
curl -s -o /dev/null -w '%{http_code}' https://<app-domain>/tmp-shots/$NAME   # must be 200
```

Verify the 200 **before** sending — a broken URL sends as a message with no image and the
client sees nothing.

**Use a random filename, always.** Not `<ticket>-<what>.png`. The reason is step 3.

### 3. Clean up after sending

```bash
docker exec <client-container> rm -rf /usr/share/nginx/html/tmp-shots
curl -sI https://<app-domain>/tmp-shots/$NAME | grep -i 'content-type\|cf-cache-status'
```

The messaging service keeps its own copy, so deleting the source costs the client nothing.

**Deleting the origin file is NOT an instant global revoke.** Measured on this stack: the
app sits behind Cloudflare and static images are served with a long `max-age`, so right
after `rm -rf` the origin correctly returned the SPA fallback while an edge POP still handed
out the full PNG. Most POPs returned 404 shortly after, but there is no purge tool wired for
this zone, so you cannot guarantee every edge copy is gone on demand.

What follows from that:
- The random filename is the real protection — an un-purged edge copy at an unguessable URL
  is not reachable by anyone who was not sent it.
- Never screenshot anything that would genuinely harm the client if it leaked: real customer
  phone numbers and addresses, payment details, staff credentials. Dev/test data is fine;
  frame production screens to exclude personal columns.
- Still delete at origin, and still check the URL afterwards — it stops the file surviving
  in the container and rules out the guessable-path case.
- A redeploy also wipes the directory, so never treat it as storage.

---

## Message shape (any channel)

One short message per completed ticket:

1. What was broken / missing — in the client's words, not the ticket's.
2. What works now.
3. Where to look (page name, not a URL path).

No ticket ids, no branch names, no file paths, no framework names. Match `client.language`
and `client.register`. Batch several tickets into one message only if they shipped together.

The screenshot carries the "where to look" — keep the text short enough that the client reads
it and then looks at the picture, rather than the picture being a footnote to an essay.
