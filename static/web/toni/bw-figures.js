/* The rule starts open on desktop and closed on a phone; native details owns interaction. */
(function () {
  'use strict';
  const rule = document.querySelector('[data-bf-rule]');
  if (rule) rule.open = window.matchMedia('(min-width: 701px)').matches;
}());
(function () {
  'use strict';
  document.addEventListener('click', async event => {
    const button = event.target.closest('[data-bf-fetch]');
    if (!button || button.disabled) return;
    const scope = button.closest('[data-bf-fetch-scope]');
    const status = scope.querySelector('[data-bf-fetch-status]');
    const root = button.closest('[data-bf-root]');
    const label = button.textContent;
    button.disabled = true;
    button.textContent = 'Fetching prices';
    scope.setAttribute('aria-busy', 'true');
    status.textContent = 'Loading price refresh';
    try {
      const response = await fetch(button.dataset.refreshUrl, {method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({items:JSON.parse(button.dataset.bfFetch), csrf_token:root.dataset.csrf})});
      const result = await response.json();
      if (!response.ok) throw new Error(result.message || 'Could not queue the price refresh');
      status.textContent = 'Price refresh queued · reload in a few minutes';
      button.textContent = label;
    } catch (error) {
      status.textContent = error.message || 'Could not queue the price refresh';
      button.textContent = 'Retry';
      button.disabled = false;
    } finally {
      scope.setAttribute('aria-busy', 'false');
    }
  });
}());
