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
    const params = (submitter) => {
      const data = new URLSearchParams();
      for (const [key, value] of new FormData(form)) data.append(key, value);
      if (submitter && submitter.name) data.append(submitter.name, submitter.value);
      // A long tick list would overrun the server's request-line limit: send the few unticked sets instead (the server reads
      // sel=except as every set but these).
      const boxes = [...form.querySelectorAll('[data-oo-copy]')];
      const off = boxes.filter((b) => !b.checked);
      if (boxes.length - off.length > 50 && off.length < boxes.length - off.length) {
        data.delete('copy');
        data.set('sel', 'except');
        data.set('omit', off.map((b) => b.value).join(','));
      }
      return data;
    };
    const query = () => form.action + '?' + params().toString();
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
        if (window.bwPartSections) window.bwPartSections(next);
        if (focus) next.querySelector(focus)?.focus({ preventScroll: true });
      } catch (_) { if (mine !== latest) return; form.submit(); }
    };
    form.addEventListener('change', (event) => {
      const target = event.target;
      const name = target.name ? `[name="${target.name}"]${target.type === 'checkbox' && target.name === 'copy' ? `[value="${target.value}"]` : target.type === 'checkbox' ? '[type=checkbox]' : ''}` : '';
      load(name ? `#bw-planning ${name}` : '');
    });
    form.addEventListener('submit', (event) => {
      if (event.submitter) {                                        // Review list and Update go through as plain links
        const data = params(event.submitter);
        if (data.get('sel') === 'except') { event.preventDefault(); location.assign(form.action + '?' + data.toString()); }
        return;
      }
      event.preventDefault();
      load('');
    });
  }
  setup();
})();
