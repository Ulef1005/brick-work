/* #57 the report's print view: the Print button opens the browser's print dialog ("Save as PDF" included), and so does the page when it has copies. */
(typeof document.querySelectorAll === 'function' ? document.querySelectorAll('[data-rp-print]') : []).forEach((button) =>
  button.addEventListener('click', () => window.print()));
if (document.body && document.body.hasAttribute('data-rp-auto')) window.print();
