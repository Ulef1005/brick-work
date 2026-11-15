/* Sections of the order list and the pull list (#315): the page works without this file (each section is a <details>). With scripts this adds
   Expand all / Collapse all, remembers which sections you opened or closed on this page (in this browser), and opens the section that holds the link's #target. */
(() => {
  'use strict';
  const key = (scope) => 'bw-part-sections:' + location.pathname + ':' + (scope.dataset.bwSectionsKey || '');
  const read = (scope) => { try { const v = JSON.parse(localStorage.getItem(key(scope))); return v && typeof v === 'object' ? v : {}; } catch (_) { return {}; } };
  const write = (scope, memory) => { try { localStorage.setItem(key(scope), JSON.stringify(memory)); } catch (_) { /* a browser that keeps nothing keeps the page's own defaults */ } };
  function setup(root) {
    (root || document).querySelectorAll('[data-bw-sections]').forEach((scope) => {
      if (scope.dataset.bwSectionsReady) return;
      scope.dataset.bwSectionsReady = '1';
      const sections = [...scope.querySelectorAll('[data-bw-section]')];
      const memory = read(scope);
      sections.forEach((section) => {
        if (typeof memory[section.dataset.bwSection] === 'boolean') section.open = memory[section.dataset.bwSection];
        const head = section.querySelector('summary');
        if (head) head.addEventListener('click', () => {                    // the click's own default flips it after this runs
          memory[section.dataset.bwSection] = !section.open;
          write(scope, memory);
        });
      });
      let target = null;
      try { target = location.hash.length > 1 ? scope.querySelector('[id="' + decodeURIComponent(location.hash.slice(1)).replace(/["\\]/g, '') + '"]') : null; } catch (error) { target = null; }       // a hand-edited or bookmarked hash may not parse
      const holder = target && target.closest('[data-bw-section]');
      if (holder) holder.open = true;
      const actions = scope.querySelector('[data-bw-sections-actions]') || (scope.parentElement && scope.parentElement.querySelector('[data-bw-sections-actions]'));
      if (!actions) return;
      if (sections.length) actions.hidden = false;
      actions.querySelectorAll('[data-bw-sections-all]').forEach((link) => link.addEventListener('click', (event) => {
        event.preventDefault();
        const open = link.dataset.bwSectionsAll === 'expand';
        sections.forEach((section) => { section.open = open; memory[section.dataset.bwSection] = open; });
        write(scope, memory);
      }));
    });
  }
  window.bwPartSections = setup;
  setup(document);
})();
