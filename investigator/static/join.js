'use strict';
const joinCode=document.getElementById('invite-code'),joinError=document.getElementById('join-error');
const fragment=new URLSearchParams(location.hash.slice(1));
if(fragment.has('invite')){joinCode.value=fragment.get('invite');history.replaceState(null,'',location.pathname);}
document.getElementById('join-form').addEventListener('submit',async event=>{
  event.preventDefault();joinError.textContent='';const button=event.currentTarget.querySelector('button');button.disabled=true;
  try{const response=await fetch('/api/access',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:joinCode.value,eligible:document.getElementById('eligible').checked})});
    if(!response.ok){const value=await response.json();throw new Error(value.error||'Unable to join.');}
    joinCode.value='';location.replace('/');
  }catch(error){joinError.textContent=error.message;}finally{button.disabled=false;}
});
