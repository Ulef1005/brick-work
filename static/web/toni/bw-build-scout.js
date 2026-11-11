/* Build Scout (#9): the wide screen selects a set in place, the filter row folds on a phone, and the buttons send Build it, Add to wishlist and Undo. */
(function () {
  var root = document.getElementById('bw-build-scout');
  if (!root) return;
  var wide = window.matchMedia('(min-width: 1024px)');
  var narrow = window.matchMedia('(max-width: 767px)');

  // a row opens its own page; on a wide screen it selects the set beside the list instead
  root.addEventListener('click', function (event) {
    var row = event.target.closest('a.bs-row');
    if (!row || !wide.matches || event.metaKey || event.ctrlKey || event.shiftKey || !row.dataset.select) return;
    event.preventDefault();
    window.location.href = row.dataset.select;
  });

  // the Filters pills are always open on a wide screen and fold behind one button on a phone
  var folds = root.querySelectorAll('[data-bs-wide]');
  function fold() {
    folds.forEach(function (details) { details.open = !narrow.matches || details.dataset.touched === '1'; });
  }
  folds.forEach(function (details) { details.addEventListener('toggle', function () { details.dataset.touched = '1'; }); });
  if (narrow.addEventListener) narrow.addEventListener('change', fold); else narrow.addListener(fold);
  fold();

  // one pop-over open at a time
  root.querySelectorAll('details.bs-pop').forEach(function (pop) {
    pop.addEventListener('toggle', function () {
      if (!pop.open) return;
      root.querySelectorAll('details.bs-pop').forEach(function (other) { if (other !== pop) other.open = false; });
    });
  });

  function send(url, body) {
    body.csrf_token = root.dataset.csrf;
    return fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, credentials: 'same-origin', body: JSON.stringify(body)})
      .then(function (response) { return response.json().catch(function () { return {message: 'Nothing was saved'}; }).then(function (data) { return {ok: response.ok, data: data}; }); });
  }

  function say(panel, text, eventId, link) {
    var box = panel.querySelector('[data-bs-message]');
    box.textContent = text + ' ';
    if (link) {
      var open = document.createElement('a');
      open.href = link;
      open.textContent = 'Open the copy';
      box.appendChild(open);
      box.appendChild(document.createTextNode(' '));
    }
    if (eventId) {
      var undo = document.createElement('button');
      undo.type = 'button';
      undo.textContent = 'Undo';
      undo.addEventListener('click', function () {
        undo.disabled = true;
        send(root.dataset.undoUrl, {event_id: eventId}).then(function (result) {
          if (result.ok) window.location.reload(); else { box.textContent = result.data.message || 'Nothing was undone'; }
        });
      });
      box.appendChild(undo);
    }
  }

  root.querySelectorAll('[data-bs-panel]').forEach(function (panel) {
    var sources = JSON.parse(root.dataset.sources || '{}');
    var build = panel.querySelector('[data-bs-build]');
    var wish = panel.querySelector('[data-bs-wish]');
    if (build) build.addEventListener('click', function () {
      build.disabled = true;
      send(root.dataset.buildUrl, sources).then(function (result) {
        if (result.ok) {
          say(panel, result.data.message, result.data.event_id, result.data.url);
          if (wish) wish.disabled = true;
        } else {
          build.disabled = false;
          say(panel, result.data.message || 'Nothing was saved');
        }
      });
    });
    if (wish) wish.addEventListener('click', function () {
      wish.disabled = true;
      send(root.dataset.wishUrl, {}).then(function (result) {
        say(panel, result.data.message || 'Nothing was saved', result.ok && !result.data.already ? result.data.event_id : null);
        if (!result.ok) wish.disabled = false;
      });
    });
  });
})();
