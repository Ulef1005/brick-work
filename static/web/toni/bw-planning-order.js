/* Order missing parts (#225): the page works without this file (a GET form, links, a download link). This only saves the Update click:
   a change in the form loads the same URL in place, keeping the scroll and the focus, and the phone folds the filters. */
(() => {
  'use strict';
  const narrow = window.matchMedia('(max-width: 1023.98px)');
  let latest = 0;                                                    // the newest request wins: an older answer is dropped
  function setup() {
    const root = document.querySelector('#bw-planning[data-screen=order]');
    if (!root) return;
    const form = root.querySelector('[data-oo-form]');
    const update = root.querySelector('[data-oo-update]');
    const box = root.querySelector('[data-oo-filters]');
    if (update) update.hidden = true;
    if (box && narrow.matches && root.dataset.step === 'choose') box.open = false;
    if (!form) return;
    const query = () => {
      const data = new URLSearchParams();
      for (const [key, value] of new FormData(form)) data.append(key, value);
      return form.action + '?' + data.toString();
    };
    const load = async (focus) => {
      const url = query();
      const mine = ++latest;
      try {
        const response = await fetch(url, { headers: { Accept: 'text/html' }, credentials: 'same-origin' });
        if (!response.ok) throw new Error(String(response.status));
        const next = new DOMParser().parseFromString(await response.text(), 'text/html').querySelector('#bw-planning[data-screen=order]');
        if (mine !== latest) return;
        if (!next) throw new Error('no page');
        const current = document.querySelector('#bw-planning[data-screen=order]') || root;
        const open = current.querySelector('[data-oo-filters]')?.open;
        current.replaceWith(next);
        history.replaceState(null, '', url);
        const fresh = next.querySelector('[data-oo-filters]');
        if (fresh && open !== undefined) fresh.open = open;
        setup();
        if (focus) next.querySelector(focus)?.focus({ preventScroll: true });
      } catch (_) { form.submit(); }
    };
    form.addEventListener('change', (event) => {
      const target = event.target;
      const name = target.name ? `[name="${target.name}"]${target.type === 'checkbox' && target.name === 'copy' ? `[value="${target.value}"]` : target.type === 'checkbox' ? '[type=checkbox]' : ''}` : '';
      load(name ? `#bw-planning ${name}` : '');
    });
    form.addEventListener('submit', (event) => {
      if (event.submitter) return;                                  // Review list and Update go through as plain links
      event.preventDefault();
      load('');
    });
  }
  setup();
})();
