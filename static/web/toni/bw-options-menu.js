// 12i desktop Options menu: Group by and Select mode, driving the View controls of the Filters panel.
document.querySelectorAll('[data-bc-options-wrap]').forEach(wrap => {
  const root = wrap.closest('[data-bc-list]') || document;
  const open = wrap.querySelector('[data-bc-options-open]');
  const menu = wrap.querySelector('[data-bc-options-menu]');
  const view = () => root.querySelector('.bc-view-group');
  const close = (focus) => { menu.hidden = true; open.setAttribute('aria-expanded', 'false'); if (focus) open.focus(); };
  const item = (role, label, checked, onPick, cls) => {
    const b = document.createElement('button');
    b.type = 'button'; b.setAttribute('role', role); b.className = cls;
    if (checked !== null) b.setAttribute('aria-checked', String(checked));
    b.textContent = label;
    b.addEventListener('click', () => { onPick(); close(true); });
    return b;
  };
  const build = () => {
    const panel = view();
    const select = root.querySelector('select[data-bc-group]');
    const picks = panel ? [...panel.querySelectorAll('[data-bc-group-pick]')] : [];
    const current = select ? select.value : '';
    const currentLabel = (picks.find(p => p.dataset.bcGroupPick === current) || {}).textContent || 'None';
    menu.replaceChildren();
    const head = document.createElement('div');
    head.className = 'bc-options-head'; head.setAttribute('role', 'presentation');
    head.textContent = 'Group by · ' + currentLabel;
    menu.append(head);
    const sw = root.querySelector('[data-bc-select][role=switch]');
    if (sw) menu.append(item('menuitemcheckbox', 'Select', sw.getAttribute('aria-checked') === 'true', () => sw.click(), 'bc-options-select'));
    const rule = document.createElement('div'); rule.className = 'bc-options-rule'; rule.setAttribute('role', 'separator');
    menu.append(rule);
    picks.forEach(p => menu.append(item('menuitemradio', p.textContent, p.dataset.bcGroupPick === current, () => p.click(), 'bc-options-choice')));
  };
  open.addEventListener('click', () => {
    if (!menu.hidden) { close(false); return; }
    build(); menu.hidden = false; open.setAttribute('aria-expanded', 'true');
    const first = menu.querySelector('[aria-checked=true]') || menu.querySelector('button');
    if (first) first.focus();
  });
  menu.addEventListener('keydown', (event) => {
    const items = [...menu.querySelectorAll('button')];
    const at = items.indexOf(document.activeElement);
    if (event.key === 'Escape') { event.preventDefault(); close(true); }
    else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      items[(at + (event.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length].focus();
    }
  });
  document.addEventListener('click', (event) => { if (!menu.hidden && !wrap.contains(event.target)) close(false); });
});
