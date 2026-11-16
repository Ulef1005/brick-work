/* 4.8c · missing-part card: stepper and Take. Posts the existing transfer through the
   collection save route, then reloads so every number comes from the server again. */
(() => {
  const clamp = (value, max) => Math.min(Math.max(1, Number(value) || 1), Math.max(1, Number(max) || 1));
  const label = value => 'Take ' + value;
  window.BrickTake = {clamp, label};
  const root = document.querySelector('#bw-collection');
  if (!root) return;
  const receiptKey = 'bw-collection-receipt';
  // The screen a receipt belongs to is the path plus the query parts that choose the copy, stock row or colour (as bw-collection.js reads it, #236).
  const screenOf = () => {
    const id = ['copy', 'stock', 'colour'].map(k => { const value = new URLSearchParams(location.search || '').get(k); return value && k + '=' + value; }).filter(Boolean).join('&');
    return id ? location.pathname + '?' + id : location.pathname;
  };
  const readResult = async response => {
    let result;
    try { result = await response.json(); } catch (_) { throw new Error('The server did not answer · try again'); }
    if (!result || typeof result !== 'object' || Array.isArray(result)) throw new Error('The server did not answer · try again');
    return result;
  };
  // #215 · Found 1 on a missing line: lowers its missing count by one through the same save route, with Undo; loose stock stays.
  // #401 · Found all: the same call with the action found-all, which sets the line's missing count to 0.
  [['[data-bc-found-one]', 'found-one'], ['[data-bc-found-all]', 'found-all']].forEach(([selector, action]) => root.querySelectorAll(selector).forEach(button => {
    const note = button.parentElement.querySelector('[data-bc-found-message]');
    button.addEventListener('click', async () => {
      if (button.disabled) return;
      const buttons = [...button.parentElement.querySelectorAll('[data-bc-found-one], [data-bc-found-all]')];
      buttons.forEach(b => { b.disabled = true; });
      if (note) note.textContent = 'Saving';
      try {
        const data = {...JSON.parse(button.dataset.identity), csrf_token: root.dataset.csrf};
        const response = await fetch(root.dataset.saveUrl.replace('ACTION', action), {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)});
        const result = await readResult(response);
        if (!response.ok) throw new Error(result.message || 'Not saved · try again');
        try { sessionStorage.setItem(receiptKey, JSON.stringify({...result, screen: screenOf()})); } catch (_) {}
        root.querySelector('[data-bc-pl]')?.bcPartEditKeepDraft?.();
        location.reload();
      } catch (error) {
        if (note) note.textContent = error.message;
        buttons.forEach(b => { b.disabled = false; });
      }
    });
  }));
  root.querySelectorAll('[data-bc-take]').forEach(box => {
    const max = Number(box.dataset.max), output = box.querySelector('[data-bc-take-value]'),
      go = box.querySelector('[data-bc-take-go]'), note = box.querySelector('[data-bc-take-message]'),
      steps = [...box.querySelectorAll('[data-bc-step]')];
    let value = clamp(max, max), busy = false;
    const show = () => {
      output.textContent = String(value);
      go.textContent = label(value);
      steps.forEach(b => { b.disabled = (Number(b.dataset.bcStep) < 0 && value <= 1) || (Number(b.dataset.bcStep) > 0 && value >= max); });
    };
    const step = delta => { if (busy) return; value = clamp(value + delta, max); show(); };
    steps.forEach(b => b.addEventListener('click', () => step(Number(b.dataset.bcStep))));
    const stepper = box.querySelector('.bc-stepper');
    stepper?.addEventListener('keydown', e => {
      const delta = {ArrowUp: 1, ArrowRight: 1, '+': 1, '=': 1, ArrowDown: -1, ArrowLeft: -1, '-': -1}[e.key];
      if (delta) { e.preventDefault(); step(delta); }
    });
    go.addEventListener('click', async () => {
      if (busy) return;
      busy = true;
      go.disabled = true;
      steps.forEach(b => { b.disabled = true; });
      if (note) note.textContent = 'Taking';
      try {
        const data = {...JSON.parse(box.dataset.identity), quantity: value, csrf_token: root.dataset.csrf};
        const response = await fetch(root.dataset.saveUrl.replace('ACTION', 'take'), {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)});
        const result = await readResult(response);
        if (!response.ok) throw new Error(result.message || 'Not saved · try again');
        try { sessionStorage.setItem(receiptKey, JSON.stringify({...result, screen: screenOf()})); } catch (_) {}
        root.querySelector('[data-bc-pl]')?.bcPartEditKeepDraft?.();
        location.reload();
      } catch (error) {
        if (note) note.textContent = error.message;
        busy = false;
        go.disabled = false;
        show();
      }
    });
    show();
  });
})();
