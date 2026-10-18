/* Execute the shipped worker: no API/write/image/transport interception. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const handlers = {}, deleted = [], network = [];
let precache, offline = false;
const fallback = {body:'offline shell'};
const cache = {async addAll(assets){precache = assets;},async match(request,options={}){const url=new URL(typeof request==='string'?request:request.url,'https://brickwork.test');return url.pathname.endsWith('offline.html') ? fallback : url.search && !options.ignoreSearch ? undefined : {body:'cached asset'};}};
const context = {URL, Promise, self:{location:{origin:'https://brickwork.test'},addEventListener(name,handler){handlers[name]=handler;},async skipWaiting(){},clients:{async claim(){}}},caches:{async open(){return cache;},async keys(){return ['brickwork-shell-old','brickwork-shell-4.1a-v1','other-app'];},async delete(name){deleted.push(name);}},async fetch(request){network.push(request.url);if(offline)throw Error('offline');return {body:'network page'};}};
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/web/toni/sw.js','utf8').replace('__ASSET_VERSION__','v1'),context);
async function lifecycle(name){let promise;handlers[name]({waitUntil(p){promise=p;}});await promise;}
function get(path,options={}){let response;handlers.fetch({request:{url:'https://brickwork.test'+path,method:'GET',mode:'navigate',...options},respondWith(p){response=p;}});return response;}
(async()=>{
 await lifecycle('install');assert(precache.includes('/static/web/toni/offline.html'));
 await lifecycle('activate');assert.deepEqual(deleted,['brickwork-shell-old']);
 for(const path of ['/api/settings','/api/v1/orders','/data/parts/1.jpg','/uploads/photo','/socket.io/?transport=polling']) assert.equal(get(path),undefined,path);
 assert.equal(get('/sets/',{method:'POST'}),undefined);
 assert.equal(get('/sets/',{method:'PUT'}),undefined);
 assert.equal(get('/static/unlisted.jpg',{mode:'no-cors'}),undefined);
 assert.equal((await get('/sets/')).body,'network page');
 assert.equal((await get('/static/web/toni/shell.css',{mode:'cors'})).body,'cached asset');
 offline=true;
 assert.equal((await get('/static/web/toni/shell.css?v=123',{mode:'cors'})).body,'cached asset');
 assert.equal((await get('/static/web/toni/bw-collection.js?v=456',{mode:'cors'})).body,'cached asset');
 offline = true;assert.equal(await get('/sets/'),fallback);
 assert.equal(get('/api/v1/orders'),undefined);
 console.log('Worker precache, old-cache cleanup, network-first HTML, offline shell and API/write/data/upload/socket exclusions passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
