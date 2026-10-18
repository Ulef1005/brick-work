/* 4.8c · missing-part card: stepper and Take. Posts the existing transfer through the
   collection save route, then reloads so every number comes from the server again. */
(() => {
  const clamp = (value, max) => Math.min(Math.max(1, Number(value) || 1), Math.max(1, Number(max) || 1));
  const label = value => 'Take ' + value;
  window.BrickTake = {clamp, label};
  const root = document.querySelector('#bw-collection');
  if (!root) return;
  const receiptKey = 'bw-collection-receipt';
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
        const result = await response.json();
        if (!response.ok) throw new Error(result.message || 'Not saved · try again');
        try { sessionStorage.setItem(receiptKey, JSON.stringify(result)); } catch (_) {}
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
