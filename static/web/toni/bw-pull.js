// The pull list (#202): the page works without this. When scripts run, choosing Show or Sort applies the search at once.
(function () {
  'use strict';
  document.querySelectorAll('[data-bp-form]').forEach(function (form) {
    form.querySelectorAll('select').forEach(function (select) {
      select.addEventListener('change', function () { form.submit(); });
    });
  });
  // The confirm is a dialog made of a link and a panel: Escape leaves it by the Cancel link (hidden on a phone, where the dimmed page above the sheet is the link).
  document.addEventListener('keydown', function (event) {
    var cancel = event.key === 'Escape' && !event.defaultPrevented && !document.querySelector('dialog[open]') && document.querySelector('#bp-confirm .bp-cancel');
    if (cancel) window.location.assign(cancel.href);
  });
})();
