'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const script=fs.readFileSync('static/web/toni/bw-collection.js','utf8').split('// Refresh only derived tiles, preserving open forms and the selected tab.')[1];
const tile={replaceWith(next){this.replacement=next;}};
const card={dataset:{thumbnailState:'pending',fileId:'7'},querySelector(){return tile;}};
const nextTile={image:'page one'};
const next={dataset:{thumbnailState:'ready',fileId:'7'},querySelector(){return nextTile;}};
const other={dataset:{thumbnailState:'ready',fileId:'9'},querySelector(){return {image:'another booklet'};}};
let calls=0,timers=[],status=[false,true];
const root={querySelector(){return card;},querySelectorAll(selector){return selector.includes('pending')&&card.dataset.thumbnailState!=='pending'?[]:[card];}};
const context={document:{querySelector(){return root;}},location:{href:'/collection/item/1?tab=extras'},setTimeout(fn){timers.push(fn);},DOMParser:class{parseFromString(){return {querySelectorAll(){return [other,next];}};}},fetch:async (url,options)=>{calls++;assert.equal(url,context.location.href);assert.equal(options.cache,'no-store');return {ok:status.shift()??true,text:async()=>'<article></article>'};}};
(async()=>{
 vm.runInNewContext(script,context);
 assert.equal(timers.length,1);
 // A failed answer keeps the polling alive; the next one is matched by file id, though the other booklet comes first.
 await timers.shift()();
 assert.equal(card.dataset.thumbnailState,'pending');assert.equal(timers.length,1);
 await timers.shift()();
 assert.equal(card.dataset.thumbnailState,'ready');
 assert.equal(tile.replacement,nextTile);
 await timers.shift()();
 assert.equal(calls,2);
 assert.equal(timers.length,0);
 console.log('Instruction previews update only pending tiles and stop when ready');
})().catch(error=>{console.error(error);process.exitCode=1;});
