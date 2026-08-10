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
