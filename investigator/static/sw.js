'use strict';
const CACHE='vi-shell-20261021-rc1';
const ASSETS=['/static/offline.html','/static/style.css','/static/icon.svg','/static/pwa-192.png','/static/pwa-512.png'];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(ASSETS)).then(()=>self.skipWaiting())));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key.startsWith('vi-shell-')&&key!==CACHE).map(key=>caches.delete(key)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',event=>{
  const url=new URL(event.request.url);
  if(event.request.method!=='GET'||url.origin!==location.origin||url.pathname.startsWith('/api/'))return;
  if(event.request.mode==='navigate'){event.respondWith(fetch(event.request).catch(()=>caches.match('/static/offline.html')));return;}
  // Online releases must not keep an indefinitely stale stylesheet.
  // Only these public static assets have an offline fallback; never API/photos.
  if(ASSETS.includes(url.pathname))event.respondWith(fetch(event.request).then(response=>{
    if(response.ok)event.waitUntil(caches.open(CACHE).then(cache=>cache.put(event.request,response.clone())));
    return response;
  }).catch(()=>caches.match(event.request)));
});
