// The pull list (#202): the page works without this. When scripts run, choosing Show or Sort applies the search at once.
(function () {
  'use strict';
  document.querySelectorAll('[data-bp-form]').forEach(function (form) {
    form.querySelectorAll('select').forEach(function (select) {
      select.addEventListener('change', function () { form.submit(); });
    });
  });
})();
