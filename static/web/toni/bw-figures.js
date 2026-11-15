/* The rule starts open on desktop and closed on a phone; native details owns interaction. */
(function () {
  'use strict';
  const rule = document.querySelector('[data-bf-rule]');
  if (rule) rule.open = window.matchMedia('(min-width: 701px)').matches;
}());
