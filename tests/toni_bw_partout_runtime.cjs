const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('static/web/toni/bw-collection.js','utf8').split('// Fetch prices in place;')[1].split('\n').slice(1).join('\n');
class Node {
  constructor(){this.dataset={};this.nodes={};this.textContent='';this.attrs={};this.children=[];}
  querySelector(s){return this.nodes[s]||null;}
  setAttribute(k,v){this.attrs[k]=v;}
  hasAttribute(k){return k in this.attrs;}
  append(n){this.children.push(n);}
  remove(){this.removed=true;}
}
async function fetchCase({priced=139,lines=145,failed=false,pending=false,states=null,detached=false,remaining=0}={}){
  const button=new Node(),scope=new Node(),status=new Node(),old=new Node(),fresh=new Node(),updated=new Node(),newButton=new Node(),newStatus=new Node();
  button.dataset={bcFetchPrices:'[1,2,3]',refreshUrl:'/refresh'};button.textContent='Fetch part prices';
  old.dataset={priced:'4',unpricedItemsCount:String(3+remaining)};updated.dataset={priced:String(priced),lines:String(lines)};
  if(pending)updated.setAttribute('data-bc-partout-pending','');
  scope.nodes['[data-bc-fetch-status]']=status;
  updated.nodes={'[data-bc-fetch-prices]':newButton,'[data-bc-fetch-status]':newStatus};
  fresh.nodes['[data-bc-partout]']=updated;
  let replaced=null,listener,calls=[],waits=0;const every=[];
  const live={replaceWith:n=>{replaced=n;every.push(n);}};scope.closest=()=>detached?null:live;
  button.closest=s=>s==='[data-bc-fetch-scope]'?scope:old;
  const context={document:{addEventListener:(event,fn)=>{listener=fn;},getElementById:()=>({dataset:{csrf:'token'}}),querySelector:()=>live,createElement:()=>new Node()},
    location:{href:'/collection/item/1?copy=Alex'},DOMParser:class{parseFromString(){return {querySelector:()=>fresh};}},
    setTimeout:fn=>{waits++;fn();},
    fetch:async(url,options)=>{
      calls.push({url,options});
      if(url==='/refresh')return {ok:!failed,json:async()=>failed?{message:'Could not queue'}:{status_urls:states?states.map((_,i)=>'/job/'+i):['/job/1']}};
      if(url.startsWith('/job/'))return {ok:true,json:async()=>({events:[{job_state:states?states[Number(url.split('/').pop())]:(waits?'done':'running')}]})};
      return {ok:true,text:async()=>'<section>Prices</section>'};
    }};
  vm.runInNewContext(source,context);
  const operation=listener({target:{closest:()=>button}});
  assert.equal(button.disabled,true);assert.equal(button.textContent,'Fetching 3 part prices');
  assert.equal(scope.attrs['aria-busy'],'true');
  // Disabled buttons cannot queue another refresh.
  await listener({target:{closest:()=>button}});
  await operation;
  assert.equal(calls.filter(c=>c.url==='/refresh').length,1);
  assert.equal(scope.attrs['aria-busy'],'false');
  if(failed){assert.equal(button.disabled,false);assert.equal(button.textContent,'Fetch part prices');assert.equal(status.textContent,'Could not queue');assert.equal(status.dataset.state,'error');assert.equal(replaced,null);return;}
  assert.equal(replaced,fresh);assert.equal(every.length,3);assert.equal(button.disabled,false);   // the Prices card, then a wish page's answer and state tag (#654)
  assert.equal(waits,states?0:1);
  const budget=states?.includes('waiting_for_budget'),bad=states?.filter(s=>['failed','cancelled'].includes(s)).length;
  assert.equal(!!newButton.removed,!budget&&!bad&&!remaining);
  const note=updated.children[0].textContent;
  if(budget)assert.match(note,/BrickLink budget reached · the worker continues later/);
  if(bad)assert.match(note,new RegExp(`${bad} price refresh jobs failed`));
  assert.equal(updated.children[0].dataset.state,bad?'error':undefined);   // a failed or cancelled job is said in the danger colour (R2-04)
  if(remaining){assert.match(note,new RegExp(`${remaining} parts remain to fetch`));assert.doesNotMatch(note,/no sales yet/);}
  else if(!budget&&!bad&&lines>priced)assert.match(note,/parts have no sales yet/);
}
(async()=>{
  await fetchCase({states:['waiting_for_budget']});await fetchCase({states:['done','failed','cancelled']});await fetchCase({detached:true});await fetchCase({remaining:201});
  await fetchCase();await fetchCase({priced:128,pending:true});await fetchCase({priced:145});await fetchCase({failed:true});
  const context={window:{},document:{querySelector:()=>null}};
  vm.runInNewContext(fs.readFileSync('static/web/toni/bw-planning.js','utf8'),context);
  const filter=context.window.BrickPlanning.filter;
  const rows=[{number:'20',partout:null},{number:'10',partout:'96.40'},{number:'2',partout:'141.00'},{number:'1',partout:null}];
  assert.deepEqual(Array.from(filter(rows,'',{},'partout'),r=>r.number),['2','10','1','20']);
  assert.deepEqual(Array.from(filter(rows,'',{},'partout',false),r=>r.number),['10','2','1','20']);
  assert.deepEqual(Array.from(filter(rows.map(r=>({...r,partout:null})),'',{},'partout'),r=>r.number),['1','2','10','20']);
  console.log('part-out runtime passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
