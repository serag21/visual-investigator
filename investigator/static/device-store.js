'use strict';
window.DeviceStore={
  async db(){return new Promise((resolve,reject)=>{const request=indexedDB.open('visual-investigator-private',1);request.onupgradeneeded=()=>request.result.createObjectStore('records',{keyPath:'id'});request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(new Error('Device storage is unavailable. Export a copy instead.'));});},
  async run(mode,operation){const db=await this.db();try{return await new Promise((resolve,reject)=>{const tx=db.transaction('records',mode);const request=operation(tx.objectStore('records'));let result;request.onsuccess=()=>{result=request.result;};tx.oncomplete=()=>resolve(result);tx.onerror=()=>reject(new Error('Device storage could not be updated.'));});}finally{db.close();}},
  async put(record){return this.run('readwrite',store=>store.put(record));},
  async remove(id){return this.run('readwrite',store=>store.delete(id));},
  async list(member){const all=await this.run('readonly',store=>store.getAll());const now=Date.now();for(const row of all)if(row.expires&&row.expires<now)await this.remove(row.id);return all.filter(row=>row.member===member&&(!row.expires||row.expires>=now));}
};
