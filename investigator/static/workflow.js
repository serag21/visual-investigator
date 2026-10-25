'use strict';
// Keep photos in this authenticated browsing context, including installed PWAs.
let inspectedPicture=null, inspectedURL=null, inspectedBlob=null, feedbackDelivery=null, sharePreview=null, shareKey=null;
let inspectionSequence=0;
let feedbackLoadedCase=null;
const workflowRender=render;
render=function(){workflowRender();renderWorkflow();};
function closeEvidence(){ inspectionSequence++;$('evidence-dialog').close(); if(inspectedURL)URL.revokeObjectURL(inspectedURL);inspectedURL=null;inspectedBlob=null;$('evidence-image').removeAttribute('src'); }
async function inspectEvidence(picture){
  const sequence=++inspectionSequence;
  inspectedPicture=picture;$('evidence-status').textContent='Opening your temporary photo…';$('evidence-focus').disabled=true;
  $('evidence-dialog').showModal();
  try{const response=await fetch(picture.url,{credentials:'same-origin',cache:'no-store'});
    if(!response.ok){let body={};try{body=await response.json();}catch{}throw new Error(body.error||'This photo is no longer in the temporary session. Restore a device save or upload it again.');}
    const blob=await response.blob();if(blob.size>6000000||!blob.type.startsWith('image/'))throw new Error('This photo could not be opened safely.');
    if(sequence!==inspectionSequence)return;
    if(inspectedURL)URL.revokeObjectURL(inspectedURL);inspectedBlob=blob;inspectedURL=URL.createObjectURL(blob);$('evidence-image').src=inspectedURL;
    $('evidence-status').textContent=`${picture.id} · private temporary evidence`;$('evidence-focus').disabled=busy||state.pictures.length>=4;
  }catch(error){if(sequence===inspectionSequence)$('evidence-status').textContent=error.message;}
}
$('evidence-close').addEventListener('click',closeEvidence);
$('evidence-dialog').addEventListener('cancel',event=>{event.preventDefault();closeEvidence();});
$('evidence-focus').addEventListener('click',async()=>{
  if(!inspectedURL||busy)return;
  const blob=inspectedBlob;clearSelected();
  selected={reuse_picture_id:inspectedPicture.id,preview_url:URL.createObjectURL(blob),region:{x:.25,y:.25,width:.5,height:.5}};
  $('preview').src=selected.preview_url;$('pending-photo').hidden=false;$('upload-empty').hidden=true;$('target-actions').hidden=false;
  closeEvidence();$('select-area').click();updateButton();$('pending-photo').scrollIntoView({behavior:'smooth',block:'center'});
  notify('Adjust the focus box, then ask your follow-up below the answer. A new evidence view will preserve the original photo. No model request yet.');
});
function renderWorkflow(){
  $('private-share').hidden=!state.turns.length;
  $('verification-record').hidden=!state.turns.length;
  $('photo-count').textContent=state.pictures.length?`${state.pictures.length} of 4 evidence views`:'Start with one photo';
  const card=$('conversation').lastElementChild, latest=state.turns.at(-1)?.finding;
  if(card&&latest){
    card.querySelector('.suggested-actions')?.remove();
    const actions=element('div',undefined,'suggested-actions');
    for(const question of latest.suggested_questions||[]){const button=element('button',question,'text-button');button.type='button';button.dataset.question=question;button.addEventListener('click',()=>{$('question').value=question;updateButton();$('question').focus();});actions.append(button);}
    if(state.pictures.length){const button=element('button','Inspect / focus the photo','text-button');button.type='button';button.addEventListener('click',()=>inspectEvidence(state.pictures.at(-1)));actions.append(button);}
    card.insertBefore(actions,$('research-record'));
  }
  renderDelivery();
  if(memberInfo&&state.investigation_id&&feedbackLoadedCase!==state.investigation_id){feedbackLoadedCase=state.investigation_id;restoreDelivery();}
}
function renderDelivery(){
  if(feedbackDelivery?.delivery==='sent'&&feedbackDelivery.body.investigation_id!==state.investigation_id){feedbackDelivery=null;$('feedback-form').reset();}
  if(feedbackDelivery?.body){$('feedback-outcome').value=feedbackDelivery.body.outcome;$('feedback-note').value=feedbackDelivery.body.note;}
  const sent=feedbackDelivery?.delivery==='sent', locked=!!feedbackDelivery;
  for(const input of $('feedback-form').elements)input.disabled=locked;
  $('feedback-retry').hidden=!feedbackDelivery||sent||feedbackDelivery.delivery==='pending';
  $('feedback-new').hidden=!sent;
  $('feedback-status').textContent=!feedbackDelivery?'':sent?`✓ Feedback received. Receipt ${feedbackDelivery.receipt}. Thank you — you can keep investigating.`:feedbackDelivery.delivery==='pending'?'Sending your feedback…':`${feedbackDelivery.body.investigation_id!==state.investigation_id?'Feedback from an earlier investigation. ':''}Delivery is uncertain. Your submission is locked to prevent duplicates. Check delivery or safely retry the same receipt.`;
}
async function saveDelivery(){try{await DeviceStore.put(feedbackDelivery);}catch{notify('Device storage is unavailable. Keep this tab open until feedback delivery is confirmed.');}}
async function deliverFeedback(checkFirst=false){
  if(!feedbackDelivery||feedbackDelivery.delivery==='pending')return;
  feedbackDelivery.delivery='pending';renderDelivery();await saveDelivery();
  try{
    let receipt;
    if(checkFirst){const response=await fetch('/api/feedback/receipt/'+feedbackDelivery.id,{credentials:'same-origin',cache:'no-store'});
      if(response.ok)receipt=await response.json();else if(response.status!==404)throw new Error('Could not check delivery. Reopen this app with your private invitation if access expired.');}
    if(!receipt){const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),20000);
      try{receipt=await api('/api/feedback',{method:'POST',body:JSON.stringify(feedbackDelivery.body),signal:controller.signal});}finally{clearTimeout(timer);}}
    feedbackDelivery.delivery='sent';feedbackDelivery.receipt=receipt.id;
  }catch(error){feedbackDelivery.delivery='uncertain';notify(error.name==='AbortError'?'Feedback confirmation timed out. Check delivery before starting another note.':error.message);}
  await saveDelivery();renderDelivery();
}
$('feedback-form').addEventListener('submit',async event=>{
  event.preventDefault();if(feedbackDelivery||!memberInfo)return;
  const body={client_key:crypto.randomUUID(),investigation_id:state.investigation_id,outcome:$('feedback-outcome').value,note:$('feedback-note').value};
  if(!body.investigation_id){notify('Refresh this investigation before sending feedback.');return;}
  if($('feedback-detail-consent').checked)body.detail={completion:$('feedback-completion').value,source_usefulness:$('feedback-sources').value,unsupported_advice:$('feedback-unsupported').value,infrastructure_problem:$('feedback-infrastructure').value};
  feedbackDelivery={id:body.client_key,kind:'feedback',member:memberInfo.id,body,created:new Date().toISOString(),expires:Date.now()+14*86400000,delivery:'ready'};
  await deliverFeedback();
});
$('feedback-retry').addEventListener('click',()=>deliverFeedback(true));
$('feedback-new').addEventListener('click',()=>{feedbackDelivery=null;$('feedback-form').reset();renderDelivery();});
async function restoreDelivery(){
  const caseId=state.investigation_id,memberId=memberInfo.id,before=feedbackDelivery;
  try{const rows=(await DeviceStore.list(memberId)).filter(r=>r.kind==='feedback'&&r.body).sort((a,b)=>b.created.localeCompare(a.created));
    if(state.investigation_id!==caseId||memberInfo.id!==memberId||feedbackDelivery!==before)return;
    feedbackDelivery=rows.find(r=>r.delivery!=='sent')||rows.find(r=>r.body.investigation_id===state.investigation_id)||null;
    if(feedbackDelivery?.delivery==='pending')feedbackDelivery.delivery='uncertain';renderDelivery();
  }catch{/* Device storage is optional. */}
}
function showSharedPreview(payload,holder){
  holder.replaceChildren();holder.append(element('p','Unverified private review evidence','small muted'));
  for(const turn of payload.turns||[]){holder.append(element('strong',turn.question||'Photo-only question'),element('p',turn.finding.answer));}
  for(const photo of payload.photos||[]){const image=element('img');image.src=`data:${photo.mime_type};base64,${photo.data}`;image.alt='Optional shared evidence preview';image.className='shared-preview-photo';holder.append(image);}
  if(payload.references)holder.append(element('p','Reference records are included in this preview.','small'));
  const details=element('details'),record=element('pre');details.append(element('summary','Review every field in this exact preview'));record.textContent=JSON.stringify({...payload,photos:(payload.photos||[]).map(({data,...metadata})=>({...metadata,data:'Photo preview shown above'}))},null,2);details.append(record);holder.append(details);
}
$('share-preview-button').addEventListener('click',async()=>{
  if(busy)return;try{const result=await api('/api/shares/preview',{method:'POST',body:JSON.stringify({photos:$('share-photos').checked})});
    sharePreview=result;shareKey=crypto.randomUUID();showSharedPreview(result.preview,$('share-preview'));$('share-confirm').checked=false;$('share-submit').disabled=true;$('share-confirm-panel').hidden=false;$('share-status').textContent=result.notice;
  }catch(error){$('share-status').textContent=error.message;}
});
$('share-confirm').addEventListener('change',()=>{$('share-submit').disabled=!$('share-confirm').checked;});
$('share-submit').addEventListener('click',async()=>{
  if(!sharePreview||!$('share-confirm').checked)return;$('share-submit').disabled=true;
  try{const result=await api('/api/shares',{method:'POST',body:JSON.stringify({token:sharePreview.token,client_key:shareKey,consent:true})});
    $('share-status').textContent=`✓ Shared privately for seven days. Receipt ${result.id}. You can remove it below.`;$('share-confirm-panel').hidden=true;await refreshShares();
  }catch(error){$('share-status').textContent=error.message+' If delivery is uncertain, review your shared cases below before retrying this same preview.';$('share-submit').disabled=false;}
});
async function refreshShares(){
  try{const result=await api('/api/shares');$('shared-cases').replaceChildren();
    for(const item of result.cases){const row=element('div',undefined,'shared-case-row');row.append(element('p',`Case ${item.investigation_id.slice(0,8)} · ${item.photo_count} shared photos · expires ${new Date(item.expires*1000).toLocaleDateString()}`,'small'));
      const view=element('button','Review shared evidence','text-button');view.type='button';view.addEventListener('click',async()=>{try{const data=await api('/api/shares/'+item.id);const box=element('div');showSharedPreview(data,box);const save=element('button','Export this private review case','text-button');save.type='button';save.addEventListener('click',()=>downloadObject(data,'private-shared-case-'+item.id+'.json'));box.append(save);row.append(box);}catch(error){notify(error.message);}});
      const remove=element('button','Remove private share','text-button');remove.type='button';remove.addEventListener('click',async()=>{if(!confirm('Remove this private review share? Older database backups may retain copies.'))return;try{await api('/api/shares/'+item.id,{method:'DELETE'});await refreshShares();}catch(error){notify(error.message);}});row.append(view,remove);$('shared-cases').append(row);
    }if(!result.cases.length)$('shared-cases').append(element('p','No active shared cases.','small'));
  }catch(error){$('share-status').textContent=error.message;}
}
$('shares-refresh').addEventListener('click',refreshShares);
function standalone(){return matchMedia('(display-mode: standalone)').matches||navigator.standalone===true;}
function installationMessage(message){$('install-status').hidden=false;$('install-status').textContent=message;}
function acceptedInstall(){try{localStorage.setItem('vi-install-accepted','yes');}catch{}$('install').hidden=true;}
function installAccepted(){try{return localStorage.getItem('vi-install-accepted')==='yes';}catch{return false;}}
window.addEventListener('beforeinstallprompt',event=>{event.preventDefault();if(standalone()||installAccepted())return;installPrompt=event;$('install').hidden=false;});
$('install').addEventListener('click',async()=>{if(!installPrompt)return;const prompt=installPrompt;installPrompt=null;$('install').hidden=true;
  try{await prompt.prompt();const choice=await prompt.userChoice;if(choice.outcome==='accepted'){acceptedInstall();installationMessage('Installation accepted. On Android, look for “Investigator” in the app drawer; long-press to add it to your home screen. Installation may take a moment.');}else installationMessage('Installation cancelled. You can keep using the browser; use its menu if you choose to install later.');}catch{installationMessage('Use your browser menu to install or add to your home screen.');}
});
window.addEventListener('appinstalled',()=>{acceptedInstall();installationMessage('Your browser reported installation. Look for “Investigator” in the app drawer or home screen.');});
$('install-help').addEventListener('click',()=>installationMessage(standalone()?'You are running in app display mode. Model analysis still requires a connection.':'Android: browser menu → Install / Add to home screen. Look for “Investigator” in the app drawer. iPhone: Share → Add to Home Screen. Different browsers may need your private invitation again.'));
window.addEventListener('vi-ready',()=>{renderWorkflow();restoreDelivery();});
if(memberInfo){renderWorkflow();restoreDelivery();}
