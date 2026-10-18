/* Shared display text; stored names and search records stay unchanged. */
(() => {
  'use strict';
  // Mirror part_size.NUMBER / DIMENSIONS, retaining decimal commas in names.
  const number = String.raw`(?:[0-9]+\s+[0-9]+/[0-9]+|[0-9]+/[0-9]+|[0-9]+(?:[.,][0-9]+)?)`;
  const dimensions = new RegExp(`(^|\\s)(${number}\\s*[x×]\\s*${number}(?:\\s*[x×]\\s*${number})?)$`, 'i');
  const partName = value => (value == null ? '' : String(value)).replace(/ - (?=[0-9])/g, ' · ');
  const nowrapTail = value => {
    const text = value == null ? '' : String(value);
    const match = text.match(dimensions);
    return match ? text.slice(0, match.index) + match[1] + match[2].replace(/\s/g, '\u00a0')
      : text.replace(/ ([^ ]*)$/, '\u00a0$1');
  };
  const resultCount = (count, noun='results') => count+' '+(count===1 && noun==='results'?'result':noun);
  window.BrickFormatting = {nowrapTail,partName,resultCount};
})();
