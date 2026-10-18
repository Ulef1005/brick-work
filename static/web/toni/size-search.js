/* #41 size-aware search, mirroring brickwork/core/size_search.py (tested against one shared table). */
(function (global) {
  const NUM = '(?:\\d+\\s+\\d+/\\d+|\\d+/\\d+|\\d+(?:\\.\\d+)?)';
  const SMALL = '(?:\\d{1,2}(?:\\s+\\d/\\d|/\\d|\\.\\d+)?)';
  const SEP = '\\s*[x×*]\\s*';
  const FULL = new RegExp('(?<![\\w./])(' + NUM + ')' + SEP + '(' + NUM + ')(?:' + SEP + '(' + NUM + '))?(?![\\w/])', 'i');
  const BARE = new RegExp('^\\s*(' + NUM + ')\\s+(' + NUM + ')(?:\\s+(' + NUM + '))?\\s*$');
  const PARTIAL = new RegExp('(?<![\\w./])(?:[x×*]\\s*(' + SMALL + ')|(' + SMALL + ')\\s*[x×*])(?![\\w/])', 'i');
  const number = text => {
    text = text.trim();
    if (text.includes('/')) {
      const at = text.lastIndexOf(' '), whole = at < 0 ? '' : text.slice(0, at), fraction = at < 0 ? text : text.slice(at + 1);
      const [a, b] = fraction.split('/');
      return (whole ? Number(whole) : 0) + Number(a) / Number(b);
    }
    return Number(text);
  };
  const fmt = v => Number.isInteger(v) ? String(v) : String(Number(v.toPrecision(6)));
  const keyOf = dims => { const values = dims.filter(Boolean).map(number); if (values.some(v => !Number.isFinite(v))) return null; return values.sort((a, b) => a - b).map(fmt).join('x'); };
  const squash = text => text.split(/\s+/).filter(Boolean).join(' ');
  function nameKey(name) { const m = FULL.exec(name || ''); return m ? keyOf([m[1], m[2], m[3]]) : null; }
  function parse(query) {
    query = (query || '').trim();
    let m = BARE.exec(query);
    if (m) return {full: keyOf([m[1], m[2], m[3]]), partial: null, rest: ''};
    m = FULL.exec(query);
    if (m) return {full: keyOf([m[1], m[2], m[3]]), partial: null, rest: squash(query.slice(0, m.index) + ' ' + query.slice(m.index + m[0].length))};
    m = PARTIAL.exec(query);
    if (m) return {full: null, partial: fmt(number(m[1] || m[2])), rest: squash(query.slice(0, m.index) + ' ' + query.slice(m.index + m[0].length))};
    return {full: null, partial: null, rest: query};
  }
  function matches(name, parsed) {
    const key = nameKey(name);
    if (parsed.full) return key === parsed.full;
    if (parsed.partial) return key !== null && key.split('x').includes(parsed.partial);
    return true;
  }
  global.BrickSize = {nameKey, parse, matches};
})(typeof window !== 'undefined' ? window : globalThis);
