const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const sandbox={window:{},document:{querySelector:()=>null}};
vm.runInNewContext(fs.readFileSync('static/web/toni/bw-storage.js','utf8'),sandbox);
const {plan,match,LIMIT}=sandbox.window.BrickStorage;
const make=(key,n,prefix)=>({key,items:Array.from({length:n},(_,i)=>({name:`${prefix} ${i}`,number:`${key}${i}`,colour:i%2?'Black':'Blue',need:String(i),rank:i}))});
const groups=[make('set',4,'Castle'),make('figure',6,'Knight'),make('part',18,'Brick')];
// Collapsed: each group shows LIMIT rows and reports what the button will reveal.
let result=plan(groups);
assert.equal(LIMIT,5);
assert.deepEqual(result.map(r=>r.shown.length),[4,5,5]);
assert.deepEqual(result.map(r=>r.more),[0,1,13]);
assert.equal(result[2].total,18);
// Expanding one group shows all of it and leaves the others collapsed.
result=plan(groups,{expanded:['part']});
assert.deepEqual(result.map(r=>r.shown.length),[4,5,18]);
// A search is never truncated, and matches name, number and colour.
result=plan(groups,{query:'brick 1'});
assert.deepEqual(result.map(r=>r.matches.length),[0,0,9]);
assert.equal(result[2].shown.length,9);
assert.equal(plan(groups,{query:'black'})[1].matches.length,3);
assert.equal(match({name:'Police Officer',number:'cty0001'},'CTY'),true);
// The kind filter keeps one group.
result=plan(groups,{kind:'figure'});
assert.deepEqual(result.map(r=>r.matches.length),[0,6,0]);
// Sort by count puts the biggest first and keeps saved order on ties.
result=plan(groups,{sort:'need'});
assert.equal(result[2].shown[0].need,'17');
result=plan(groups,{sort:'rank'});assert.equal(result[2].shown[0].rank,0);
// Nothing matching leaves every group empty.
assert.equal(plan(groups,{query:'zzz'}).every(r=>r.matches.length===0),true);
// Checked items survive a search or filter that no longer matches them, and a move would carry them.
const sel=make('set',4,'Castle');sel.items[0].checked=true;sel.items[1].checked=true;
for(const opts of [{query:'castle 3'},{query:'zzz'},{kind:'figure'}]){
  const [r]=plan([sel,make('figure',2,'Knight')],opts);
  assert.equal(r.shown.includes(sel.items[0])&&r.shown.includes(sel.items[1]),true,JSON.stringify(opts));
}
const [one]=plan([sel],{query:'castle 3'});
assert.equal(one.shown.map(i=>i.name).join(),'Castle 3,Castle 0,Castle 1');
assert.equal(one.matches.length,1);
const big=make('part',18,'Brick');big.items[17].checked=true;
assert.equal(plan([big])[0].shown.includes(big.items[17]),true);
// Links inside a row keep working outside select mode; the row itself still swallows the click.
const link={closest:s=>s==='a'?{}:null},plain={closest:()=>null};
assert.equal(sandbox.window.BrickStorage.blocksClick(false,link),false);
assert.equal(sandbox.window.BrickStorage.blocksClick(false,plain),true);
assert.equal(sandbox.window.BrickStorage.blocksClick(true,plain),false);
// The count and the empty state follow what is shown: a kept selection is one item, not "0 items".
const kept=make('set',3,'Castle');kept.items[1].checked=true;
assert.equal(sandbox.window.BrickStorage.shownCount(plan([kept],{query:'zzz'})),1);
assert.equal(sandbox.window.BrickStorage.shownCount(plan([make('set',3,'Castle')],{query:'zzz'})),0);
// A checked lot checks and disables its in-storage parts, and the summary says what moves.
const {carry,moveSummary}=sandbox.window.BrickStorage;
const rows=[{entity:'lot',id:'L1',lot:'',kind:'part',checked:true},{entity:'stock',id:'a',lot:'L1',kind:'part',checked:false},{entity:'stock',id:'b',lot:'L1',kind:'part',checked:false},{entity:'stock',id:'c',lot:'',kind:'part',checked:false}];
carry(rows);
assert.deepEqual(rows.map(r=>[r.checked,Boolean(r.disabled)]).join('|'),'true,false|true,true|true,true|false,false');
assert.equal(moveSummary(rows.filter(r=>r.checked)),'1 lot · 2 parts');
rows[0].checked=false;carry(rows);
assert.equal(rows.some(r=>r.checked||r.disabled),false);
assert.equal(moveSummary([{entity:'copy'},{entity:'copy'},{entity:'stock',kind:'figure'},{entity:'stock',kind:'other'}]),'2 sets · 1 figure · 1 other item');
assert.equal(moveSummary([]),'0 items');
console.log('Storage runtime passed');
