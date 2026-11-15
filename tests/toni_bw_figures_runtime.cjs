'use strict';
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync(require('path').join(__dirname, '../static/web/toni/bw-figures.js'), 'utf8');
(async () => {
  for (const desktop of [true, false]) {
    const rule = {};
    vm.runInNewContext(source, {document:{querySelector:()=>rule,addEventListener:()=>{}}, window:{matchMedia:q=>{assert.equal(q,'(min-width: 701px)'); return {matches:desktop};}}});
    assert.equal(rule.open, desktop);
  }
  let click, fail=false, unreadable=false, sent;
  const status={textContent:''}, scope={querySelector:()=>status,setAttribute:(k,v)=>scope[k]=v};
  const root={dataset:{csrf:'synthetic'}};
  const button={dataset:{bfFetch:'[1,2]',refreshUrl:'/planning/action/refresh'}, textContent:'Fetch 2 prices',disabled:false,
    closest:s=>s==='[data-bf-root]'?root:scope};
  vm.runInNewContext(source, {document:{querySelector:()=>null,addEventListener:(name,fn)=>click=fn}, fetch:async (url,options)=>{
    sent=JSON.parse(options.body); assert.equal(url,button.dataset.refreshUrl);
    return {ok:!fail,json:async()=>{if(unreadable)throw new Error('Unreadable response');return {message:'Price source unavailable'};}};
  }});
  const event={target:{closest:()=>button}};
  await click(event);
  assert.equal(sent.csrf_token,'synthetic'); assert.equal(sent.items.length,2);
  assert.equal(scope['aria-busy'],'false'); assert.equal(button.disabled,true); assert.match(status.textContent,/queued/);
  button.disabled=false; fail=true;
  await click(event);
  assert.equal(button.disabled,false); assert.equal(button.textContent,'Retry'); assert.match(status.textContent,/unavailable/);
  unreadable=true; await click(event);
  assert.equal(button.disabled,false); assert.match(status.textContent,/Unreadable/);
  console.log('Figures disclosure, loading, success, retry and unreadable response passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
