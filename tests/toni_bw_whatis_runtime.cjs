/* #45 What is this? card: owned summary, colours with storage, and the actions. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Node{constructor(tag){this.tagName=tag;this.children=[];this.style={};this.className='';this.textContent='';this.events={};this.dataset={};}
 append(...n){this.children.push(...n);} replaceChildren(){this.children=[];} addEventListener(k,f){this.events[k]=f;}
 querySelector(){return null;} all(){return this.children.flatMap(c=>[c,...(c.all?c.all():[])]);}}
const root=new Node('section');root.dataset={url:'/detect',csrf:'x'};const file=new Node('input'),status=new Node('p'),results=new Node('div');
root.querySelector=s=>({'[data-wi-file]':file,'[data-wi-status]':status,'[data-wi-results]':results})[s]||null;
const window={};const document={querySelector:s=>s==='[data-wi-root]'?root:null,createElement:t=>new Node(t)};
vm.runInNewContext(fs.readFileSync('static/web/toni/bw-whatis.js','utf8'),{document,window,FormData:class{append(){}},fetch:async()=>({ok:true,json:async()=>({candidates:[]})})});
const card=window.BrickWhatIs.card({item_type:'P',item_no:'3001',name:'Brick 2 x 4',score:0.91,image:7,owned_summary:{total:23,text:'You have 23 in 2 colours: Black 14, Red 9 (Bin A3)',needed_count:1,colours:[{name:'Black',rgb:'05131D',quantity:14,storages:[]},{name:'Red',rgb:'C91A09',quantity:9,storages:['Bin A3']}]}});
const nodes=card.all();
assert.ok(nodes.some(n=>n.textContent==='You have 23 in 2 colours: Black 14, Red 9 (Bin A3)'));
assert.deepEqual(nodes.filter(n=>n.className==='wi-chip').map(n=>[n.textContent,n.style.color]),[['Black','#FAFAF8'],['Red','#FAFAF8']]);
assert.ok(nodes.some(n=>n.textContent==='Not stored'));
const links=nodes.filter(n=>n.tagName==='a');
assert.deepEqual(links.map(a=>a.textContent),['Add to stock','Open part','Fill a missing part · 1 copy']);
assert.equal(links[0].href,'/manage/add?type=P&where=loose&number=3001');
const none=window.BrickWhatIs.card({item_type:'M',item_no:'fig9',name:'Figure',score:0.5,owned_summary:{total:0,text:'Not in your collection',colours:[],needed_count:0}});
assert.ok(none.all().some(n=>n.textContent==='Not in your collection'&&n.className.includes('wi-none')));
console.log('What is this? card: owned summary, colours and actions passed');
