// xml.mjs — just enough XML to read Namecheap's responses.
//
// Every answer is XML, and nearly all of the data sits in attributes on
// self-closing tags. Pulling in a parser would break the rule that a skill folder
// copied anywhere still runs with no install step, so this reads the one shape
// Namecheap actually sends. It is not a general XML parser and should not be used
// as one.

const NAMED = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'" };

export function decode(text) {
  return String(text).replace(/&(#x[0-9a-f]+|#\d+|amp|lt|gt|quot|apos);/gi, (whole, body) => {
    if (body[0] === '#') {
      const code = body[1].toLowerCase() === 'x' ? parseInt(body.slice(2), 16) : parseInt(body.slice(1), 10);
      return Number.isFinite(code) ? String.fromCodePoint(code) : whole;
    }
    return NAMED[body.toLowerCase()] ?? whole;
  });
}

/** `a="1" b="2"` to `{ a: '1', b: '2' }`. */
export function attrs(text) {
  const out = {};
  for (const m of String(text || '').matchAll(/([\w:.-]+)="([^"]*)"/g)) out[m[1]] = decode(m[2]);
  return out;
}

/**
 * Every `<tag ...>` in the document, as `{ attrs, text, raw }`. Case is ignored
 * because Namecheap is not consistent about it between commands.
 */
export function elements(xml, tag) {
  const pattern = new RegExp(`<${tag}\\b([^>]*?)(?:/>|>([\\s\\S]*?)</${tag}>)`, 'gi');
  return [...String(xml).matchAll(pattern)].map((m) => ({
    attrs: attrs(m[1]),
    text: decode((m[2] || '').trim()),
    raw: m[0],
  }));
}

export const first = (xml, tag) => elements(xml, tag)[0];

/** What every response carries, whatever the command. */
export function parseResponse(xml) {
  const head = /<ApiResponse\b[^>]*\bStatus="(\w+)"/i.exec(xml);
  if (!head) return null;
  return {
    ok: head[1].toUpperCase() === 'OK',
    errors: elements(xml, 'Error').map((e) => ({ code: e.attrs.Number, message: e.text })),
    warnings: elements(xml, 'Warning').map((w) => ({ code: w.attrs.Number, message: w.text })),
  };
}
