// Three small behaviours. Nothing here is required to read the page.

/* copy a command ---------------------------------------------------------- */

for (const btn of document.querySelectorAll('.cmd')) {
  const label = btn.querySelector('.cmd-c');
  btn.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(btn.dataset.copy);
      btn.classList.add('is-copied');
      label.textContent = 'copied';
    } catch {
      // Clipboard blocked (insecure context, or the user said no). Select the
      // text so the keyboard still gets them there.
      const r = document.createRange();
      r.selectNodeContents(btn.querySelector('code'));
      getSelection().removeAllRanges();
      getSelection().addRange(r);
      label.textContent = 'select + copy';
    }
    setTimeout(() => {
      btn.classList.remove('is-copied');
      label.textContent = 'copy';
    }, 1600);
  });
}

/* trace one agent's wire -------------------------------------------------- */

const rig = document.querySelector('.rig');
if (rig) {
  const wireFor = (id) => rig.querySelector(`.wire[data-agent="${id}"]`);
  for (const label of rig.querySelectorAll('.wlabel')) {
    const id = label.dataset.agent;
    const light = () => wireFor(id)?.classList.add('is-lit');
    const dim = () => wireFor(id)?.classList.remove('is-lit');
    label.addEventListener('mouseenter', light);
    label.addEventListener('mouseleave', dim);
  }
}

/* filter the catalog ------------------------------------------------------ */

const q = document.getElementById('q');
if (q) {
  const cards = [...document.querySelectorAll('#results .card')];
  const chips = [...document.querySelectorAll('.chip')];
  const empty = document.getElementById('empty');
  let type = 'all';

  const apply = () => {
    const term = q.value.trim().toLowerCase();
    let shown = 0;
    for (const c of cards) {
      const okType = type === 'all' || c.dataset.type === type;
      const okTerm = !term || (c.dataset.search || '').includes(term);
      const on = okType && okTerm;
      c.hidden = !on;
      if (on) shown++;
    }
    empty.hidden = shown > 0;
  };

  q.addEventListener('input', apply);
  for (const chip of chips) {
    chip.addEventListener('click', () => {
      chips.forEach((c) => c.classList.toggle('is-on', c === chip));
      type = chip.dataset.type;
      apply();
    });
  }
  document.getElementById('clear')?.addEventListener('click', () => {
    q.value = '';
    type = 'all';
    chips.forEach((c) => c.classList.toggle('is-on', c.dataset.type === 'all'));
    apply();
    q.focus();
  });
}

/* theme: auto → light → dark ---------------------------------------------- */
// Default is the system preference. An explicit choice persists and wins over
// it in both directions; clearing the choice returns to following the system.

{
  const btn = document.getElementById('theme');
  const label = document.getElementById('theme-label');
  const root = document.documentElement;
  const ORDER = ['auto', 'light', 'dark'];

  const read = () => {
    try {
      const v = localStorage.getItem('theme');
      return v === 'light' || v === 'dark' ? v : 'auto';
    } catch { return 'auto'; }
  };

  const paint = (mode) => {
    if (mode === 'auto') root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', mode);
    if (label) label.textContent = mode;
    btn?.setAttribute('aria-label', `Colour theme: ${mode}. Click to change.`);
  };

  paint(read());

  btn?.addEventListener('click', () => {
    const next = ORDER[(ORDER.indexOf(read()) + 1) % ORDER.length];
    try {
      if (next === 'auto') localStorage.removeItem('theme');
      else localStorage.setItem('theme', next);
    } catch { /* private mode — the choice just won't survive a reload */ }
    paint(next);
  });

  // Another tab changed the preference.
  addEventListener('storage', (e) => { if (e.key === 'theme') paint(read()); });
}
