/* The screens switch (App Docs Standard, screenshot standard): a tutorial's screenshot is a <picture> with a phone source and a desktop image.
   By default the reader's own screen picks (the media query on the source); the switch serves a reader who uses the app on another device.
   The choice is kept in this browser only. Nothing here is needed to read the page: without scripts the media query still picks. */
(function () {
  var KEY = 'bw-docs-screens';
  var pictures = document.querySelectorAll('picture[data-bw-screens]');
  if (!pictures.length) return;
  var narrow = window.matchMedia('(max-width: 600px)');
  var saved = function () { try { return localStorage.getItem(KEY) || 'auto'; } catch (e) { return 'auto'; } };
  var apply = function (mode) {
    pictures.forEach(function (picture) {
      var source = picture.querySelector('source');
      if (!source.dataset.auto) source.dataset.auto = source.getAttribute('media');
      source.setAttribute('media', mode === 'phone' ? 'all' : mode === 'desktop' ? 'not all' : source.dataset.auto);
      if (mode === 'phone' && !narrow.matches) picture.setAttribute('data-forced', 'phone'); else picture.removeAttribute('data-forced');
    });
    document.querySelectorAll('.bw-screens button').forEach(function (button) {
      button.setAttribute('aria-pressed', String(button.dataset.mode === mode));
    });
  };
  var bar = document.createElement('div');
  bar.className = 'bw-screens';
  bar.setAttribute('role', 'group');
  bar.setAttribute('aria-label', 'Screenshots');
  bar.innerHTML = '<span>Screenshots:</span>' + [['auto', 'Match my screen'], ['desktop', 'Desktop'], ['phone', 'Phone']].map(function (m) {
    return '<button type="button" data-mode="' + m[0] + '">' + m[1] + '</button>';
  }).join('');
  bar.addEventListener('click', function (event) {
    var button = event.target.closest('button');
    if (!button) return;
    try { localStorage.setItem(KEY, button.dataset.mode); } catch (e) { /* the choice just is not kept */ }
    apply(button.dataset.mode);
  });
  var heading = document.querySelector('.md-content__inner h1');
  if (heading) heading.insertAdjacentElement('afterend', bar); else document.querySelector('.md-content__inner').prepend(bar);
  narrow.addEventListener('change', function () { apply(saved()); });
  apply(saved());
})();
