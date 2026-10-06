const CACHE='signal-owner-v1';
const ASSETS=['./','./index.html','./manifest.json','./icon.svg'];
self.addEventListener('install',e=>{
  e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS)));
  self.skipWaiting();
});
self.addEventListener('activate',e=>{
  e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim()));
});
self.addEventListener('fetch',e=>{
  if(e.request.method!=='GET') return;
  if(e.request.mode==='navigate'){
    e.respondWith(fetch(e.request,{cache:'no-store'}).then(r=>{
      const copy=r.clone(); caches.open(CACHE).then(c=>c.put(e.request,copy)); return r;
    }).catch(()=>caches.match(e.request).then(x=>x||caches.match('./'))));
    return;
  }
  e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)));
});
self.addEventListener('push',e=>{
  let data={};
  try{data=e.data?e.data.json():{};}catch(_){data={body:e.data?e.data.text():""};}
  const title=data.title||'Signal';
  const options={body:data.body||'Νέα ενημέρωση είναι διαθέσιμη.',icon:'./icon.svg',badge:'./icon.svg',tag:data.tag||'signal-update',renotify:true,data:{url:data.url||'./'}};
  e.waitUntil(self.registration.showNotification(title,options));
});
self.addEventListener('notificationclick',e=>{
  e.notification.close();
  const target=(e.notification.data&&e.notification.data.url)||'./';
  e.waitUntil(clients.matchAll({type:'window',includeUncontrolled:true}).then(list=>{
    for(const client of list){
      if('focus' in client){
        if('navigate' in client) client.navigate(target);
        return client.focus();
      }
    }
    return clients.openWindow?clients.openWindow(target):null;
  }));
});