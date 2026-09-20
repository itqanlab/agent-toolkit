// Parser for CHANGELOG.md, the per-item history every skill, plugin and MCP server keeps.
//
// The file is written for people and read by agents, so the format is strict enough to
// parse without guessing. It is a subset of Keep a Changelog:
//
//   # Changelog
//   Latest: <site address of this same file>
//
//   ## [1.2.0] - 2026-09-20
//   ### Added
//   - One line per change. Say what the user can now do.
//
// Newest version first. `## [Unreleased]` may sit above the newest release.
// A `### Breaking` section means the user has to do something when they update.

export const SECTIONS = ['Breaking', 'Added', 'Changed', 'Deprecated', 'Removed', 'Fixed', 'Security'];

const SEMVER = /^(\d+)\.(\d+)\.(\d+)$/;

export function compareVersions(a, b) {
  const pa = a.match(SEMVER).slice(1).map(Number);
  const pb = b.match(SEMVER).slice(1).map(Number);
  for (let i = 0; i < 3; i++) if (pa[i] !== pb[i]) return pa[i] - pb[i];
  return 0;
}

const isRealDate = (s) => {
  const d = new Date(`${s}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === s;
};

// Returns { latestUrl, releases, unreleased, errors }.
// A release is { version, date, sections: { Added: [..] }, breaking }.
export function parseChangelog(source) {
  const text = source.replace(/\r\n?/g, '\n'); // tolerate CRLF from a Windows checkout
  const errors = [];
  const releases = [];
  let unreleased = null;
  let latestUrl = null;
  let current = null;
  let section = null;
  let lastBullet = null;

  const lines = text.split('\n');
  lines.forEach((line, idx) => {
    const at = `line ${idx + 1}`;
    const latest = line.match(/^Latest:\s*(\S+)\s*$/);
    if (latest && !current) { latestUrl = latest[1]; return; }

    const h2 = line.match(/^## (.*)$/);
    if (h2) {
      section = null; lastBullet = null;
      const head = h2[1].trim();
      if (head === '[Unreleased]') {
        if (releases.length || unreleased) errors.push(`${at}: [Unreleased] must be the first entry`);
        current = unreleased = { version: 'Unreleased', date: null, sections: {}, breaking: false };
        return;
      }
      const m = head.match(/^\[([^\]]+)\] - (\d{4}-\d{2}-\d{2})$/);
      if (!m) { errors.push(`${at}: heading must be "## [x.y.z] - YYYY-MM-DD", found "${line}"`); current = null; return; }
      const [, version, date] = m;
      if (!SEMVER.test(version)) errors.push(`${at}: "${version}" is not a version like 1.2.3`);
      if (!isRealDate(date)) errors.push(`${at}: "${date}" is not a real date`);
      const prev = releases[releases.length - 1];
      if (prev && SEMVER.test(version) && SEMVER.test(prev.version) && compareVersions(version, prev.version) >= 0) {
        errors.push(`${at}: ${version} must be older than ${prev.version} (newest first)`);
      }
      if (prev && isRealDate(date) && date > prev.date) {
        errors.push(`${at}: ${version} is dated ${date}, after ${prev.version} (${prev.date})`);
      }
      current = { version, date, sections: {}, breaking: false };
      releases.push(current);
      return;
    }

    const h3 = line.match(/^### (.*)$/);
    if (h3) {
      lastBullet = null;
      if (!current) { errors.push(`${at}: section before any version heading`); return; }
      section = h3[1].trim();
      if (!SECTIONS.includes(section)) {
        errors.push(`${at}: unknown section "${section}" (use: ${SECTIONS.join(', ')})`);
        section = null;
        return;
      }
      if (section === 'Breaking') current.breaking = true;
      current.sections[section] = current.sections[section] || [];
      return;
    }

    const bullet = line.match(/^- (.+)$/);
    if (bullet) {
      if (!current || !section) { errors.push(`${at}: a bullet needs a version and a section above it`); return; }
      current.sections[section].push(bullet[1].trim());
      lastBullet = current.sections[section];
      return;
    }
    // A wrapped line belongs to the bullet above it.
    if (/^\s{2,}\S/.test(line) && lastBullet) {
      lastBullet[lastBullet.length - 1] += ` ${line.trim()}`;
    }
  });

  for (const r of releases) {
    const count = Object.values(r.sections).reduce((n, list) => n + list.length, 0);
    if (count === 0) errors.push(`${r.version}: no changes listed`);
  }
  if (!latestUrl) errors.push('missing the "Latest: <address>" line under the title');
  if (!releases.length) errors.push('no release entries');

  return { latestUrl, releases, unreleased, errors };
}
