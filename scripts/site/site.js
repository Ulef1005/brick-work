/* Progressive enhancement: all prose and walkthrough steps remain in the HTML. */
(() => {
  const root = document.documentElement;
  const preference = window.matchMedia('(prefers-color-scheme: dark)');
  const toggle = document.querySelector('[data-theme-toggle]');
  let choice = null;
  try {
    const stored = localStorage.getItem('bw-site-theme');
    if (stored === 'light' || stored === 'dark') choice = stored;
  } catch (_) { /* Storage may be unavailable. */ }
  function theme() {
    const dark = choice ? choice === 'dark' : preference.matches;
    root.classList.toggle('tw-dark', dark);
    root.classList.toggle('tw-light', !dark);
    // Keep picture sources in sync with an explicit override as well as the OS.
    document.querySelectorAll('picture source').forEach(source => {
      source.media = choice ? (dark ? 'all' : 'not all') : '(prefers-color-scheme: dark)';
    });
    toggle.textContent = dark ? 'Dark' : 'Light';
    toggle.setAttribute('aria-label', `Switch to ${dark ? 'light' : 'dark'} theme`);
  }
  theme();
  preference.addEventListener('change', theme);
  toggle.addEventListener('click', () => {
    choice = root.classList.contains('tw-dark') ? 'light' : 'dark';
    try { localStorage.setItem('bw-site-theme', choice); } catch (_) { /* Optional. */ }
    theme();
  });
  document.querySelectorAll('[data-device]').forEach(button => {
    button.addEventListener('click', () => {
      root.classList.toggle('desktop-device', button.dataset.device === 'desktop');
      document.querySelectorAll('[data-device]').forEach(other => {
        other.setAttribute('aria-pressed', String(other === button));
      });
    });
  });
  document.querySelectorAll('[data-walkthrough]').forEach(flow => {
    const steps = [...flow.querySelectorAll('.steps li')];
    const frames = [...flow.querySelectorAll('[data-frame]')];
    let current = 0;
    const buttons = steps.map((step, index) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.append(step.querySelector('.step-copy'));
      button.addEventListener('click', () => show(index));
      step.append(button);
      return button;
    });
    function show(index) {
      current = (index + steps.length) % steps.length;
      buttons.forEach((button, i) => {
        if (i === current) button.setAttribute('aria-current', 'step');
        else button.removeAttribute('aria-current');
      });
      frames.forEach((frame, i) => { frame.hidden = i !== current; });
      flow.querySelector('[data-step-status]').textContent =
        `Step ${current + 1} of ${steps.length} · ${steps[current].querySelector('h3').textContent}`;
    }
    flow.querySelector('[data-back]').addEventListener('click', () => show(current - 1));
    flow.querySelector('[data-next]').addEventListener('click', () => show(current + 1));
    show(0);
  });
  root.classList.add('js');
})();
