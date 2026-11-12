// Set detection on the lot page (#200): the page works without this. When scripts run, turning "Ignore common parts" on or off applies the filters at once.
(function () {
  'use strict';
  document.querySelectorAll('[data-detect-form]').forEach(function (form) {
    var toggle = form.querySelector('input[name="ignore_common"]');
    if (toggle) toggle.addEventListener('change', function () { form.submit(); });
  });
})();
