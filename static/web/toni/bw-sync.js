/* 12n Collection sync: tabs and search on a plan, the live count on the main button, and busy states. */
(function () {
  const plans = typeof document.querySelectorAll === 'function' ? document.querySelectorAll('[data-sy-plan]') : [];
  plans.forEach((form) => {
    const rows = [...form.querySelectorAll('[data-sy-row]')];
    const tabs = [...form.querySelectorAll('[data-sy-tab]')];
    const search = form.querySelector('[data-sy-search]');
    const submit = form.querySelector('[data-sy-submit]');
    const total = form.querySelector('[data-sy-total]');
    const requests = form.querySelector('[data-sy-requests]');
    let tab = 'all';
    const hasConflictTab = tabs.some((b) => b.dataset.syTab === 'conflict');
    const inTab = (row) => tab === 'all' || row.dataset.state === tab || (row.dataset.also || '').split(' ').includes(tab);
    const filter = () => {
      const q = (search && search.value || '').trim().toLowerCase();
      rows.forEach((row) => {
        if (row.dataset.state === 'conflict' && !hasConflictTab) return;  // conflicts sit in their own card, and have no tab on this page
        row.hidden = !(inTab(row) && (!q || (row.dataset.name || '').toLowerCase().includes(q)));
      });
      form.querySelectorAll('[data-sy-card]').forEach((card) => {     // a card whose rows are all hidden goes with them
        const inside = [...card.querySelectorAll('[data-sy-row]')];
        card.hidden = inside.length > 0 && inside.every((row) => row.hidden);
      });
    };
    const count = () => {
      const changedLists = [...form.querySelectorAll('[data-sy-listpick]')].filter((pick) => pick.value !== 'keep' && pick.value !== 'skip').length;   // a rename or a drop is a change
      const ticked = form.querySelectorAll('[data-sy-tick]:checked').length + [...form.querySelectorAll('[data-sy-pick]')].filter((pick) => pick.value).length + changedLists;
      if (submit) {
        const verb = submit.dataset.syVerb;
        submit.textContent = ticked ? verb + ' ' + ticked + ('syPlain' in submit.dataset ? '' : ticked === 1 ? ' change' : ' changes') : verb;
        submit.disabled = ticked === 0;
      }
      if (requests) requests.textContent = String(form.dataset.syDirection === 'run' ? form.querySelectorAll('[data-sy-send]:checked').length : ticked);
      if (total) total.textContent = 'syOf' in total.dataset ? ticked + ' of ' + total.dataset.syOf + ' chosen' : ticked + ' ticked';
    };
    tabs.forEach((button) => button.addEventListener('click', () => {
      tab = button.dataset.syTab;
      tabs.forEach((b) => b.setAttribute('aria-pressed', String(b === button)));
      filter();
    }));
    if (search) search.addEventListener('input', filter);
    form.addEventListener('change', count);
    count();
  });
  const files = typeof document.querySelectorAll === 'function' ? document.querySelectorAll('[data-bt-file]') : [];
  files.forEach((input) => input.addEventListener('change', () => {
    const name = input.parentElement && input.parentElement.querySelector('[data-bt-file-name]');
    if (name) name.textContent = input.files && input.files[0] ? input.files[0].name : 'No file chosen';
  }));
  const busy = typeof document.querySelectorAll === 'function' ? document.querySelectorAll('form[data-sy-busy]') : [];
  busy.forEach((form) => form.addEventListener('submit', (event) => {
    if (form.getAttribute('aria-busy') === 'true') { event.preventDefault(); return; }
    form.setAttribute('aria-busy', 'true');
    const button = event.submitter || form.querySelector('button[data-busy-label]');
    if (button && button.dataset.busyLabel) {
      button.textContent = button.dataset.busyLabel;
      setTimeout(() => { button.disabled = true; }, 0);
    }
  }));
})();
