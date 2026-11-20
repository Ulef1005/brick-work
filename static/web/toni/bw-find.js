// Find instructions (#484): choosing a region shows its links at once; without this script the hidden "Show links" button (or Enter) does it.
document.querySelectorAll('[data-find-region]').forEach(function (select) {
  select.addEventListener('change', function () { if (select.form) select.form.requestSubmit(); });
});
