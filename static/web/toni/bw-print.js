/* #43: the Print button opens the browser's print dialog ("Save as PDF" included). */
(typeof document.querySelectorAll === 'function' ? document.querySelectorAll('[data-pr-print]') : []).forEach((button) =>
  button.addEventListener('click', () => window.print()));
