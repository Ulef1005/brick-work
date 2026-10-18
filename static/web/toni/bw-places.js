/* #46 Purchase locations: choosing a Kind saves it at once (one receipt, Undo in History). */
(typeof document.querySelectorAll === 'function' ? document.querySelectorAll('[data-pl-kind]') : []).forEach((select) => {
  select.addEventListener('change', () => {
    const form = select.closest('form');
    if (form && typeof form.requestSubmit === 'function') form.requestSubmit();
  });
});
